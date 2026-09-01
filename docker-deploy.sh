#!/bin/bash

# AgentCore  Intelligent customer service system - Docker deployment script


set -e

#  Color definition
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

#  Configuration
PROJECT_NAME="agentcore"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"

#  Function:Print information
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

#  Function: Check dependencies
check_dependencies() {
    print_info " Check dependencies..."

    if ! command -v docker &> /dev/null; then
        print_error "Docker  Not installed, Please install Docker first"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose  Not installed, Please install Docker Compose first"
        exit 1
    fi

    print_info " Dependency check completed"
}

#  Function:Create necessary directories
create_directories() {
    print_info "Create necessary directories..."

    mkdir -p data/chroma
    mkdir -p logs
    mkdir -p config/nginx/ssl
    mkdir -p config/grafana/provisioning
    mkdir -p config/grafana/dashboards
    mkdir -p config/alerts

    print_info " Directory creation completed"
}

#  Function: Check environment variables
check_env_file() {
    print_info " Check environment variable configuration..."

    if [ ! -f "$ENV_FILE" ]; then
        print_warn ".env  File does not exist,Creating from .env.example..."

        if [ -f ".env.example" ]; then
            cp .env.example .env
            print_info " .env file created, Please edit configuration"
            print_warn "Special attention: Please set ANTHROPIC_API_KEY"
        else
            print_error ".env.example  File does not exist"
            exit 1
        fi
    else
        print_info "Environment variable configuration file already exists"
    fi
}

#  Function:Build image
build_images() {
    print_info "Building a Docker image..."

    docker-compose build --no-cache

    print_info "Image construction completed"
}

#  Function: Start service
start_services() {
    print_info "Starting service..."

    docker-compose up -d

    print_info "Service startup completed"
}

#  Function: Stop service
stop_services() {
    print_info " Stop service..."

    docker-compose down

    print_info "Service has stopped"
}

#  Function:Restart service
restart_services() {
    print_info "Restart service..."

    docker-compose restart

    print_info "Service restarted"
}

#  Function: View service status
status_services() {
    print_info " Service status:"

    docker-compose ps
}

#  Function:View log
view_logs() {
    local service=$1

    if [ -z "$service" ]; then
        print_info " View all service logs..."
        docker-compose logs -f
    else
        print_info "View $service Service log..."
        docker-compose logs -f "$service"
    fi
}

#  Function:Health Check
health_check() {
    print_info "Perform health check..."

    #  Waiting for service to start
    sleep 10

    #  Check main application
    if curl -sf http://localhost:8000/health > /dev/null; then
        print_info "✓  Main App Health"
    else
        print_error "✗  Main application is unhealthy"
    fi

    #  Check Redis
    if docker-compose exec -T redis redis-cli ping | grep -q PONG; then
        print_info "✓ Redis Health"
    else
        print_error "✗ Redis Unhealthy"
    fi

    #  Check ChromaDB
    if curl -sf http://localhost:8001/api/v1/heartbeat > /dev/null; then
        print_info "✓ ChromaDB Health"
    else
        print_error "✗ ChromaDB  Unhealthy"
    fi

    #  Check Prometheus
    if curl -sf http://localhost:9090/-/healthy > /dev/null; then
        print_info "✓ Prometheus Health"
    else
        print_error "✗ Prometheus  Unhealthy"
    fi
}

#  Function: Clean up resources
cleanup() {
    print_warn " Clean all resources (Includes data volume)..."

    read -p " Confirm cleanup? This will delete all data (y/N): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker-compose down -v
        print_info " Cleanup completed"
    else
        print_info " Cleanup canceled"
    fi
}

#  Function: Backup data
backup_data() {
    local backup_dir="backups/$(date +%Y%m%d_%H%M%S)"

    print_info " Back up data to $backup_dir..."

    mkdir -p "$backup_dir"

    #  Back up Redis data
    docker-compose exec -T redis redis-cli SAVE
    docker cp agentcore-redis:/data/dump.rdb "$backup_dir/"

    #  Back up ChromaDB data
    docker cp agentcore-chromadb:/chroma/chroma "$backup_dir/"

    #  Backup configuration
    cp .env "$backup_dir/"
    cp -r config "$backup_dir/"

    print_info " Backup completed: $backup_dir"
}

#  Function:Recover data
restore_data() {
    local backup_dir=$1

    if [ -z "$backup_dir" ]; then
        print_error " Please specify the backup directory"
        exit 1
    fi

    if [ ! -d "$backup_dir" ]; then
        print_error " The backup directory does not exist: $backup_dir"
        exit 1
    fi

    print_warn "From $backup_dir Recover data..."
    read -p " Confirm recovery?This will overwrite existing data (y/N): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        #  Stop service
        docker-compose stop

        # Recover Redis data
        docker cp "$backup_dir/dump.rdb" agentcore-redis:/data/

        # Restore ChromaDB data
        docker cp "$backup_dir/chroma" agentcore-chromadb:/chroma/

        # Restore configuration
        cp "$backup_dir/.env" .env
        rm -rf config
        cp -r "$backup_dir/config" config

        #  Start service
        docker-compose start

        print_info "Restore completed"
    else
        print_info "Restore canceled"
    fi
}

#  Function:Display help information
show_help() {
    cat << EOF
AgentCore  Intelligent customer service system - Docker deployment script

 Usage: ./docker-deploy.sh [ Command]

 Command:
    install     Initializing the installation ( Check dependencies, Create directory,Build image)
    start        Start all services
    stop         Stop all services
    restart     Restart all services
    status      View service status
    logs         View service log ( Optional specified service name)
    health       Perform health check
    build        Rebuild the image
    cleanup      Clean up all resources (Includes data)
    backup       Backup data
    restore     Recover data ( Need to specify the backup directory)
    help        Display this help message

 Example:
    ./docker-deploy.sh install
    ./docker-deploy.sh start
    ./docker-deploy.sh logs agentcore
    ./docker-deploy.sh backup
    ./docker-deploy.sh restore backups/20231201_120000

 Environment variables:
     Configure relevant parameters in the .env file

EOF
}

#  Main function
main() {
    case "${1:-help}" in
        install)
            check_dependencies
            check_env_file
            create_directories
            build_images
            print_info " Installation completed!Run './docker-deploy.sh start'  Start service"
            ;;
        start)
            check_env_file
            start_services
            health_check
            ;;
        stop)
            stop_services
            ;;
        restart)
            restart_services
            ;;
        status)
            status_services
            ;;
        logs)
            view_logs "$2"
            ;;
        health)
            health_check
            ;;
        build)
            build_images
            ;;
        cleanup)
            cleanup
            ;;
        backup)
            backup_data
            ;;
        restore)
            restore_data "$2"
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            show_help
            exit 1
            ;;
    esac
}

# Execute main function
main "$@"