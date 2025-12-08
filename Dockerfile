# 🏗 Stage 1: Build the Go binary
FROM golang:1.25.5-alpine AS builder

WORKDIR /app

# Copy go.mod and install dependencies
COPY go.mod go.sum ./
RUN go mod download

# Copy the source code
COPY main.go ./

# Build the application
# Use -ldflags to strip debug info and reduce memory footprint
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o webhook main.go

# 🏗 Stage 2: Create a minimal runtime environment
FROM alpine:latest

# Install CA certificates (needed for MySQL & HTTPS requests)
RUN apk --no-cache add ca-certificates tzdata

WORKDIR /app

# Copy the compiled Go binary from the builder stage
COPY --from=builder /app/webhook .

USER nobody

COPY *.json ./

# Run the webhook
ENTRYPOINT ["/app/webhook"]
