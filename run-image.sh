#!/bin/bash

# AgentCore Image run script
#  Provides multiple run configuration options

set -e

#  Configuration
IMAGE_NAME="agentcore"
CONTAINER_NAME="agentcore-app"
VERSION=${VERSION:-latest}
REGISTRY=""  #  If the image is in a private repository, Set to registry.example.com/

# Default port mapping
API_PORT=8000
PROMETHEUS_PORT=9090

# Default volume mapping
DATA_DIR="./data"
LOGS_DIR="./logs"
CONFIG_DIR="./config"

#  Color definition
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    cat << EOF
AgentCore Docker Image running tool

 Usage: ./run-image.sh [ Command] [ Options]

 Command:
    run              Run container (Default mode)
    run-dev          Running a development mode container
    run-test         Run test container
    stop             Stop container
    restart          Restart container
    logs             View container logs
    shell           Enter container shell
    status           View container status
    clean            Clean containers and data
    help            Show this help

 Options:
    --detach         Running in the background
    --ports          Custom port mapping
    --env-file      Specify environment variable file
    --volume         Custom volume mapping
    --name           Custom container name
    --network        Custom network

 Example:
    ./run-image.sh run
    ./run-image.sh run-dev --detach
    ./run-image.sh run --env-file .env.prod
    ./run-image.sh logs
    ./run-image.sh shell

 Production environment operation:
    ./run-image.sh run \\
        --env-file .env.prod \\
        --detach \\
        --restart unless-stopped

 Development environment operation:
    ./run-image.sh run-dev \\
        --volume ./src:/app/src \\
        --detach

EOF
}

#  Create necessary directories
ensure_directories() {
    mkdir -p "$DATA_DIR"
    mkdir -p "$LOGS_DIR"
    mkdir -p "$CONFIG_DIR"
}

#  Running container
run_container() {
    local mode=$1
    shift || true

    local detach=false
    local env_file=".env"
    local custom_ports=""
    local custom_volumes=""
    local container_name="$CONTAINER_NAME"
    local restart_policy="no"

    #  Parsing parameters
    while [[ $# -gt 0 ]]; do
        case $1 in
            --detach|-d)
                detach=true
                shift
                ;;
            --env-file)
                env_file="$2"
                shift 2
                ;;
            --ports|-p)
                custom_ports="-p $2"
                shift 2
                ;;
            --volume|-v)
                custom_volumes="$custom_volumes -v $2"
                shift 2
                ;;
            --name)
                container_name="$2"
                shift 2
                ;;
            --restart)
                restart_policy="$2"
                shift 2
                ;;
            *)
                shift
                ;;
        esac
    done

    ensure_directories

    #  Check environment files
    if [ ! -f "$env_file" ]; then
        print_warn " Environment file $env_file  does not exist, Use default configuration"
        env_file=""
    else
        env_file="--env-file $env_file"
    fi

    # Basic configuration
    local image_tag="${REGISTRY}${IMAGE_NAME}:${VERSION}"
    local default_ports="-p ${API_PORT}:8000 -p ${PROMETHEUS_PORT}:9090"
    local default_volumes="-v ${DATA_DIR}:/app/data -v ${LOGS_DIR}:/app/logs -v ${CONFIG_DIR}:/app/config"

    #  Adjust configuration according to mode
    case $mode in
        dev)
            print_info " Running a development mode container"
            default_ports="$default_ports -p 5678:5678"  #  Add debug port
            restart_policy="no"
            ;;
        test)
            print_info " Running test container"
            restart_policy="no"
            ;;
        prod)
            print_info " Running a production mode container"
            restart_policy="unless-stopped"
            ;;
        *)
            print_info " Running standard containers"
            ;;
    esac

    #  Build run command
    local run_cmd="docker run"

    if [ "$detach" = true ]; then
        run_cmd="$run_cmd -d"
    fi

    run_cmd="$run_cmd --name $container_name"
    run_cmd="$run_cmd --restart $restart_policy"
    run_cmd="$run_cmd $default_ports $custom_ports"
    run_cmd="$run_cmd $default_volumes $custom_volumes"
    run_cmd="$run_cmd $env_file"
    run_cmd="$run_cmd $image_tag"

    print_info " Start container: $container_name"
    print_info " Mirror: $image_tag"

    #  Check if container already exists
    if docker ps -a --format '{{.Names}}' | grep -q "^${container_name}$"; then
        print_warn " Container $container_name  already exists, Stop and delete first"
        docker stop "$container_name" 2>/dev/null || true
        docker rm "$container_name" 2>/dev/null || true
    fi

    #  Running container
    eval $run_cmd

    if [ $? -eq 0 ]; then
        print_info "✓  Container started successfully"
        print_info "APIAddress: http://localhost:${API_PORT}"
        print_info "Prometheus: http://localhost:${PROMETHEUS_PORT}"

        if [ "$detach" = true ]; then
            print_info " Container running in background"
            print_info "View log: ./run-image.sh logs"
        fi
    else
        print_error "✗  Container startup failed"
        exit 1
    fi
}

#  Stop container
stop_container() {
    local name=${1:-$CONTAINER_NAME}

    print_info " Stop container: $name"

    if docker ps --format '{{.Names}}' | grep -q "^${name}$"; then
        docker stop "$name"
        print_info "✓  Container stopped"
    else
        print_warn "Container $name  Not running"
    fi
}

#  Restart container
restart_container() {
    local name=${1:-$CONTAINER_NAME}

    print_info " Restart container: $name"

    if docker ps -a --format '{{.Names}}' | grep -q "^${name}$"; then
        docker restart "$name"
        print_info "✓  Container restarted"
    else
        print_error " Container $name  does not exist"
        exit 1
    fi
}

# View log
view_logs() {
    local name=${1:-$CONTAINER_NAME}
    local follow=${2:-true}

    if [ "$follow" = "true" ]; then
        docker logs -f "$name"
    else
        docker logs "$name"
    fi
}

# Enter container shell
enter_shell() {
    local name=${1:-$CONTAINER_NAME}

    print_info "Enter container shell: $name"

    if docker ps --format '{{.Names}}' | grep -q "^${name}$"; then
        docker exec -it "$name" /bin/bash
    else
        print_error " Container $name  Not running"
        exit 1
    fi
}

# View status
show_status() {
    local name=${1:-$CONTAINER_NAME}

    print_info " Container status: $name"

    if docker ps -a --format '{{.Names}}' | grep -q "^${name}$"; then
        docker ps -a --filter "name=$name" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        print_warn "Container $name  does not exist"
    fi
}

#  Clean container
clean_container() {
    local name=${1:-$CONTAINER_NAME}

    print_warn " Clean containers and data volumes"

    read -p " Confirm cleanup? This will delete the container and data (y/N): " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker stop "$name" 2>/dev/null || true
        docker rm "$name" 2>/dev/null || true
        print_info "✓  Container cleaned"
    else
        print_info " Cleanup canceled"
    fi
}

# Main function
main() {
    local command=${1:-run}
    shift || true

    case $command in
        run)
            run_container "" "$@"
            ;;
        run-dev)
            run_container "dev" "$@"
            ;;
        run-test)
            run_container "test" "$@"
            ;;
        run-prod)
            run_container "prod" "$@"
            ;;
        stop)
            stop_container "$1"
            ;;
        restart)
            restart_container "$1"
            ;;
        logs)
            if [ "$1" = "--no-follow" ]; then
                view_logs "$2" "false"
            else
                view_logs "$1" "true"
            fi
            ;;
        shell)
            enter_shell "$1"
            ;;
        status)
            show_status "$1"
            ;;
        clean)
            clean_container "$1"
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

# Execute main function
main "$@"