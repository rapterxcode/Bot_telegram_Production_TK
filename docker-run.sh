#!/bin/bash

# TK-Signal Bot Docker Management Script
# Usage: ./docker-run.sh [command]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if required files exist
check_requirements() {
    print_info "Checking requirements..."
    
    if [ ! -f ".env" ]; then
        print_error ".env file not found!"
        exit 1
    fi
    
    if [ ! -f "credentials.json" ]; then
        print_error "credentials.json file not found!"
        exit 1
    fi
    
    if [ ! -f "requirements.txt" ]; then
        print_error "requirements.txt file not found!"
        exit 1
    fi
    
    print_success "All required files found"
}

# Build the Docker image
build() {
    print_info "Building Docker image..."
    docker compose build --no-cache
    print_success "Docker image built successfully"
}

# Start the bot in development mode
start_dev() {
    check_requirements
    print_info "Starting TK-Signal Bot in development mode..."
    docker compose up -d
    print_success "Bot started successfully"
    print_info "Use 'docker compose logs -f' to view logs"
}

# Start the bot in production mode
start_prod() {
    check_requirements
    if [ ! -f ".env.production" ]; then
        print_warning ".env.production not found, using .env"
        cp .env .env.production
    fi
    
    print_info "Starting TK-Signal Bot in production mode..."
    docker compose -f docker-compose.prod.yml up -d
    print_success "Bot started successfully in production mode"
    print_info "Use 'docker compose -f docker-compose.prod.yml logs -f' to view logs"
}

# Stop the bot
stop() {
    print_info "Stopping TK-Signal Bot..."
    docker compose down
    docker compose -f docker-compose.prod.yml down 2>/dev/null || true
    print_success "Bot stopped successfully"
}

# Restart the bot
restart() {
    print_info "Restarting TK-Signal Bot..."
    stop
    sleep 2
    start_dev
}

# View logs
logs() {
    if docker compose ps -q tksignal-bot-prod >/dev/null 2>&1; then
        print_info "Showing production logs..."
        docker compose -f docker-compose.prod.yml logs -f
    else
        print_info "Showing development logs..."
        docker compose logs -f
    fi
}

# Show status
status() {
    print_info "Container status:"
    docker compose ps
    docker compose -f docker-compose.prod.yml ps 2>/dev/null || true
}

# Update and restart
update() {
    print_info "Updating TK-Signal Bot..."
    stop
    build
    start_dev
    print_success "Bot updated and restarted"
}

# Clean up
cleanup() {
    print_info "Cleaning up Docker resources..."
    docker compose down --rmi all --volumes --remove-orphans
    docker compose -f docker-compose.prod.yml down --rmi all --volumes --remove-orphans 2>/dev/null || true
    docker system prune -f
    print_success "Cleanup completed"
}

# Show help
show_help() {
    echo "TK-Signal Bot Docker Management Script"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  build       Build Docker image"
    echo "  dev         Start in development mode"
    echo "  prod        Start in production mode"
    echo "  stop        Stop the bot"
    echo "  restart     Restart the bot"
    echo "  logs        View logs"
    echo "  status      Show container status"
    echo "  update      Update and restart bot"
    echo "  cleanup     Clean up all Docker resources"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 dev      # Start development environment"
    echo "  $0 prod     # Start production environment"
    echo "  $0 logs     # View real-time logs"
    echo "  $0 stop     # Stop all containers"
}

# Main command handling
case "${1:-help}" in
    "build")
        build
        ;;
    "dev")
        start_dev
        ;;
    "prod")
        start_prod
        ;;
    "stop")
        stop
        ;;
    "restart")
        restart
        ;;
    "logs")
        logs
        ;;
    "status")
        status
        ;;
    "update")
        update
        ;;
    "cleanup")
        cleanup
        ;;
    "help"|"--help"|"-h")
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac