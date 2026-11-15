#!/bin/bash
# Build a Docker image and push it to Google Artifact Registry
#
# Usage:
#   ./build.sh [TAG]
#
# Examples:
#   ./build.sh
#   ./build.sh v1
#   ./build.sh $(git rev-parse --short HEAD)

set -e

# --- Configuration ---
PROJECT_ID="knightmare-9qwrr0"
REGION="us-central1"
REPOSITORY="knightmare-backend"
IMAGE_NAME="knightmare-backend"

# Use provided tag or fall back to short git hash or "latest"
TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo "latest")}"

# Full Artifact Registry image path
IMAGE_TAG="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${TAG}"

echo "=========================================================="
echo "Project:     ${PROJECT_ID}"
echo "Region:      ${REGION}"
echo "Repository:  ${REPOSITORY}"
echo "Image Name:  ${IMAGE_NAME}"
echo "Tag:         ${TAG}"
echo "Full Image:  ${IMAGE_TAG}"
echo "=========================================================="
echo ""

# Build
echo "🔨 Building image..."
docker build -t "${IMAGE_TAG}" .

# Push
echo ""
echo "📤 Pushing image to Artifact Registry..."
docker push "${IMAGE_TAG}"

echo ""
echo "✅ Build and push complete."
