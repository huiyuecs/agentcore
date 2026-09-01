#!/bin/bash

# AgentCore Image build script
#  Provides multiple build options for different scenarios

set -e

#  Color definition
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

#  Configuration
IMAGE_NAME="agentcore"
REGISTRY=""  #  If you need to push to a private warehouse, Set to registry.example.com/
VERSION=${VERSION:-latest}
BUILD_ARGS=""

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Show usage help
show_help() {
    cat << EOF
AgentCore Docker Image building tool

 Usage: ./build-image.sh [ Command] [ Options]

 Command:
    build            Build default image
    build-prod       Build production image
    build-dev       Build development image
    build-test       Build test image
    push             Push the image to the warehouse
    tag              Add tags to images
    clean            Clean build cache
    help            Show this help

 Options:
    --no-cache       Disable cache build
    --platform      Specified platform (linux/amd64, linux/arm64)
    --registry      Specify the image warehouse
    --version       Specify version number

 Example:
    ./build-image.sh build-prod
    ./build-image.sh build --no-cache
    ./build-image.sh build --platform linux/amd64,linux/arm64
    ./build-image.sh push --registry my-registry.com
    ./build-image.sh tag --version v1.0.0

EOF
}

# Build image
build_image() {
    local target=$1
    local no_cache=$2
    local platforms=$3

    print_step "Start building image: ${IMAGE_NAME}:${VERSION}"

    #  Build parameters
    build_cmd="docker build"

    # Add target
    if [ -n "$target" ]; then
        build_cmd="$build_cmd --target $target"
    fi

    # Add cache option
    if [ "$no_cache" = "true" ]; then
        build_cmd="$build_cmd --no-cache"
        print_warn " Disable build cache"
    fi

    #  Add multi-platform support
    if [ -n "$platforms" ]; then
        build_cmd="$build_cmd --platform $platforms"
        print_info " Build platform: $platforms"
    fi

    #  Add build parameters
    if [ -n "$BUILD_ARGS" ]; then
        build_cmd="$build_cmd $BUILD_ARGS"
    fi

    #  Execute build
    full_tag="${REGISTRY}${IMAGE_NAME}:${VERSION}"
    build_cmd="$build_cmd -t $full_tag -t ${REGISTRY}${IMAGE_NAME}:latest ."

    print_info "Execute command: $build_cmd"
    eval $build_cmd

    if [ $? -eq 0 ]; then
        print_info "✓ Image built successfully: $full_tag"
    else
        print_error "✗  Image build failed"
        exit 1
    fi
}

#  Push image
push_image() {
    local registry=$1

    if [ -n "$registry" ]; then
        REGISTRY="$registry/"
    fi

    print_step " Push the image to the warehouse"

    #  Push version label
    docker push ${REGISTRY}${IMAGE_NAME}:${VERSION}

    #  Push the latest tags
    docker push ${REGISTRY}${IMAGE_NAME}:latest

    print_info "✓  Image push successful"
}

#  Add tags to images
tag_image() {
    local new_version=$1

    print_step " Add tags to images: $new_version"

    docker tag ${REGISTRY}${IMAGE_NAME}:${VERSION} ${REGISTRY}${IMAGE_NAME}:${new_version}

    print_info "✓  Tag added successfully: ${REGISTRY}${IMAGE_NAME}:${new_version}"
}

#  Clean build cache
clean_build_cache() {
    print_step " Clean Docker build cache"

    docker builder prune -f

    print_info "✓  Build cache cleared"
}

#  Parsing parameters
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --no-cache)
                NO_CACHE=true
                shift
                ;;
            --platform)
                PLATFORMS="$2"
                shift 2
                ;;
            --registry)
                REGISTRY="$2"
                shift 2
                ;;
            --version)
                VERSION="$2"
                shift 2
                ;;
            *)
                shift
                ;;
        esac
    done
}

# Main function
main() {
    local command=${1:-help}
    shift || true

    #  Parse options
    parse_args "$@"

    case $command in
        build)
            build_image "" "$NO_CACHE" "$PLATFORMS"
            ;;
        build-prod)
            build_image "production" "$NO_CACHE" "$PLATFORMS"
            ;;
        build-dev)
            build_image "development" "$NO_CACHE" "$PLATFORMS"
            ;;
        build-test)
            build_image "test" "$NO_CACHE" "$PLATFORMS"
            ;;
        push)
            shift
            push_image "$1"
            ;;
        tag)
            shift
            tag_image "$1"
            ;;
        clean)
            clean_build_cache
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