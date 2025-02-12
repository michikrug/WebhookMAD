package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/driver/mysql"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type EncounterData struct {
	ID                      string  `gorm:"primaryKey" json:"encounter_id"`
	PokestopID              *string `json:"pokestop_id"`
	SpawnIDString           string  `gorm:"-" json:"spawnpoint_id"` // Temporary field for JSON decoding
	SpawnID                 *int64
	Lat                     float32 `json:"latitude"`
	Lon                     float32 `json:"longitude"`
	Weight                  *float32
	Size                    *int
	Height                  *float32
	ExpireTimestamp         *int `json:"disappear_time"`
	Updated                 *int
	PokemonID               int
	Move1                   *int `gorm:"column:move_1" json:"move_1"`
	Move2                   *int `gorm:"column:move_2" json:"move_2"`
	Gender                  *int
	CP                      *int
	AtkIV                   *int `json:"individual_attack"`
	DefIV                   *int `json:"individual_defense"`
	StaIV                   *int `json:"individual_stamina"`
	Form                    *int
	Level                   *int
	Weather                 *int
	Costume                 *int
	FirstSeenTimestamp      int  `json:"first_seen"`
	Changed                 int  `json:"last_modified_time"`
	ExpireTimestampVerified bool `json:"disappear_time_verified"`
	DisplayPokemonID        *int
	SeenType                *string
	Shiny                   *bool
	Username                *string
	Capture1                *float32 `gorm:"column:capture_1" json:"capture_1"`
	Capture2                *float32 `gorm:"column:capture_2" json:"capture_2"`
	Capture3                *float32 `gorm:"column:capture_3" json:"capture_3"`
	IsEvent                 int
	IV                      *float32
}

var (
	db            *gorm.DB
	queue         = make(chan []EncounterData, 1000)
	webhookSecret = os.Getenv("WEBHOOK_SECRET")
	pokeAlarmURL  = os.Getenv("POKEALARM_URL")
)

func initDB() {
	dsn := fmt.Sprintf("%s:%s@tcp(%s)/%s?charset=utf8mb4&parseTime=True&loc=Local",
		os.Getenv("DB_USER"), os.Getenv("DB_PASSWORD"), os.Getenv("DB_HOST"), os.Getenv("DB_NAME"))
	var err error
	db, err = gorm.Open(mysql.Open(dsn), &gorm.Config{})
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	log.Println("Database connection established.")
}

func sendToPokeAlarm(data []byte) {
	if pokeAlarmURL == "" {
		return
	}
	go func() {
		resp, err := http.Post(pokeAlarmURL, "application/json", bytes.NewBuffer(data))
		if err != nil {
			log.Printf("Failed to send data to PokeAlarm: %v", err)
			return
		}
		defer resp.Body.Close()
		log.Printf("Forwarded data to PokeAlarm with status: %d", resp.StatusCode)
	}()
}

func webhookHandler(c *gin.Context) {
	secret := c.Param("secret")
	if secret != webhookSecret {
		c.JSON(http.StatusForbidden, gin.H{"error": "Invalid secret"})
		return
	}

	data, err := c.GetRawData()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Failed to read request body"})
		return
	}

	sendToPokeAlarm(data)

	var encounters []EncounterData
	if err := json.Unmarshal(data, &encounters); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid JSON: " + err.Error()})
		return
	}

	currentTime := int(time.Now().Unix())
	for i := range encounters {
		spawnID, err := strconv.ParseInt(encounters[i].SpawnIDString, 16, 64)
		if err == nil {
			encounters[i].SpawnID = &spawnID
		} else {
			log.Printf("Failed to convert spawnID %s: %v", encounters[i].SpawnIDString, err)
			encounters[i].SpawnID = nil
		}

		encounters[i].Updated = &currentTime

		if encounters[i].AtkIV != nil && encounters[i].DefIV != nil && encounters[i].StaIV != nil {
			iv := float32((*encounters[i].AtkIV+*encounters[i].DefIV+*encounters[i].StaIV)*100) / 45.0
			encounters[i].IV = &iv
		}
	}

	select {
	case queue <- encounters:
		log.Printf("Queued batch of %d records", len(encounters))
	default:
		log.Println("Queue is full, dropping batch")
	}

	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func queryWorker() {
	for batch := range queue {
		if err := db.Clauses(clause.OnConflict{UpdateAll: true}).Create(&batch).Error; err != nil {
			log.Printf("Database error: %v", err)
		} else {
			log.Printf("Processed batch of %d records", len(batch))
		}
	}
}

func main() {
	initDB()
	go queryWorker()

	r := gin.Default()
	r.POST("/webhook/:secret", webhookHandler)
	srv := &http.Server{Addr: ":8000", Handler: r}

	// Start server in a goroutine
	go func() {
		log.Println("Starting server on port 8000")
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	// Set up channel to listen for interrupt or terminate signals
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("Shutting down server...")

	// Create a deadline to wait
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Fatalf("Server shutdown error: %v", err)
	}
}
