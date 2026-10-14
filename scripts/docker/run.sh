#!/usr/bin/env bash
set -euo pipefail

ros_distro=${1:?Usage: bash scripts/docker/run.sh humble|jazzy TRANSPORT_SOURCE HAND_SOURCE}
case "$ros_distro" in
  humble|jazzy) ;;
  *) echo "Supported distributions: humble, jazzy" >&2; exit 2 ;;
esac
transport_source=$(realpath "${2:?Provide the Transport main source directory}")
hand_source=$(realpath "${3:?Provide the Hand Python main source directory}")
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_image="linkerbot-hand-ros-test:${ros_distro}"
base_image=${ROS_TEST_BASE_IMAGE:-ros:${ros_distro}-ros-base}
asset_options=()
if [[ -n "${LINKERBOT_HAND_ASSETS_ROOT:-}" ]]; then
  asset_source=$(realpath "${LINKERBOT_HAND_ASSETS_ROOT}")
  if [[ ! -d "$asset_source" ]]; then
    echo "LINKERBOT_HAND_ASSETS_ROOT must be a directory" >&2
    exit 2
  fi
  asset_options=(
    --mount "type=bind,source=${asset_source},target=/sources/assets,readonly"
    --env LINKERBOT_HAND_ASSETS_ROOT=/sources/assets
  )
fi

docker build --network "${ROS_TEST_BUILD_NETWORK:-default}" \
  --build-arg HTTP_PROXY --build-arg HTTPS_PROXY --build-arg NO_PROXY \
  --build-arg "ROS_IMAGE=${base_image}" \
  -f "${repo_root}/scripts/docker/Dockerfile" -t "$test_image" "$repo_root"
docker run --rm --init \
  --env "EXPECTED_ROS_DISTRO=${ros_distro}" \
  --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-87}" \
  --mount "type=bind,source=${repo_root},target=/sources/ros,readonly" \
  --mount "type=bind,source=${transport_source},target=/sources/transport,readonly" \
  --mount "type=bind,source=${hand_source},target=/sources/hand,readonly" \
  "${asset_options[@]}" \
  "$test_image"
