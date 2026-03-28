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

PROD_CONTAINER_NAME="tksignal-bot-prod"
DEV_CONTAINER_NAME="tksignal-bot"
PROD_ENV_FILE=".env.production"

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

# Resolve which env file production should use
set_prod_env_file() {
    PROD_ENV_FILE=".env.production"
    if [ ! -f "${PROD_ENV_FILE}" ]; then
        PROD_ENV_FILE=".env"
        return 1
    fi
    return 0
}

# Check if required files exist
check_requirements() {
    local env_file="$1"

    print_info "Checking requirements..."

    if [ ! -f "${env_file}" ]; then
        print_error "${env_file} file not found!"
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

dev_compose() {
    APP_ENV_FILE=".env" \
    ENVIRONMENT="development" \
    COMPOSE_CONTAINER_NAME="${DEV_CONTAINER_NAME}" \
    COMPOSE_RESTART_POLICY="unless-stopped" \
    COMPOSE_CPU_LIMIT="0.5" \
    COMPOSE_MEMORY_LIMIT="512M" \
    COMPOSE_CPU_RESERVATION="0.1" \
    COMPOSE_MEMORY_RESERVATION="128M" \
    COMPOSE_LOG_MAX_SIZE="10m" \
    COMPOSE_LOG_MAX_FILE="3" \
    COMPOSE_NETWORK_NAME="tksignal-network" \
    docker compose "$@"
}

prod_compose() {
    set_prod_env_file >/dev/null 2>&1 || true

    APP_ENV_FILE="${PROD_ENV_FILE}" \
    ENVIRONMENT="production" \
    COMPOSE_CONTAINER_NAME="${PROD_CONTAINER_NAME}" \
    COMPOSE_RESTART_POLICY="always" \
    HEALTHCHECK_RETRIES="5" \
    HEALTHCHECK_START_PERIOD="60s" \
    COMPOSE_CPU_LIMIT="1.0" \
    COMPOSE_MEMORY_LIMIT="1G" \
    COMPOSE_CPU_RESERVATION="0.2" \
    COMPOSE_MEMORY_RESERVATION="256M" \
    COMPOSE_LOG_MAX_SIZE="50m" \
    COMPOSE_LOG_MAX_FILE="5" \
    COMPOSE_NETWORK_NAME="tksignal-prod-network" \
    WATCHTOWER_CONTAINER_NAME="tksignal-watchtower" \
    WATCHTOWER_TARGET_CONTAINER="${PROD_CONTAINER_NAME}" \
    docker compose --profile production "$@"
}

is_prod_running() {
    docker ps --format '{{.Names}}' | grep -qx "${PROD_CONTAINER_NAME}"
}

# Build the Docker image
build() {
    print_info "Building Docker image..."
    dev_compose build --no-cache
    print_success "Docker image built successfully"
}

# Start the bot in development mode
start_dev() {
    check_requirements ".env"
    print_info "Starting TK-Signal Bot in development mode..."
    dev_compose up -d
    print_success "Bot started successfully"
    print_info "Use 'docker compose logs -f' to view logs"
}

# Start the bot in production mode
start_prod() {
    if ! set_prod_env_file; then
        print_warning ".env.production not found, using .env"
    fi

    check_requirements "${PROD_ENV_FILE}"
    print_info "Starting TK-Signal Bot in production mode..."
    prod_compose up -d
    print_success "Bot started successfully in production mode"
    print_info "Use 'docker compose --profile production logs -f' to view logs"
}

# Stop the bot
stop() {
    print_info "Stopping TK-Signal Bot..."
    dev_compose down 2>/dev/null || true
    prod_compose down 2>/dev/null || true
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
    if is_prod_running; then
        print_info "Showing production logs..."
        prod_compose logs -f
    else
        print_info "Showing development logs..."
        dev_compose logs -f
    fi
}

# Show status
status() {
    print_info "Development status:"
    dev_compose ps 2>/dev/null || true

    print_info "Production status:"
    prod_compose ps 2>/dev/null || true
}

# Update and restart
update() {
    print_info "Updating TK-Signal Bot..."
    local target_mode="dev"

    if is_prod_running; then
        target_mode="prod"
    fi

    stop
    build
    if [ "${target_mode}" = "prod" ]; then
        start_prod
    else
        start_dev
    fi
    print_success "Bot updated and restarted"
}

# Clean up
cleanup() {
    print_info "Cleaning up Docker resources..."
    dev_compose down --rmi all --volumes --remove-orphans 2>/dev/null || true
    prod_compose down --rmi all --volumes --remove-orphans 2>/dev/null || true
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
    echo "Notes:"
    echo "  - Uses a single docker-compose.yml for both development and production"
    echo "  - Production mode reads .env.production when present, otherwise falls back to .env"
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
