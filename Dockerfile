# 🏗 Stage 1: Build the Go binary
FROM golang:1.23 AS builder

WORKDIR /app

# Copy go.mod and install dependencies
COPY go.mod go.sum ./
RUN go mod download

# Copy the source code
COPY main.go ./

# Build the application
RUN CGO_ENABLED=0 GOOS=linux go build -o webhook main.go

# 🏗 Stage 2: Create a minimal runtime environment
FROM alpine:latest

# Install CA certificates (needed for MySQL & HTTPS requests)
RUN apk --no-cache add ca-certificates tzdata

WORKDIR /app

# Copy the compiled Go binary from the builder stage
COPY --from=builder /app/webhook .

USER nobody

# Run the webhook
ENTRYPOINT ["/app/webhook"]
