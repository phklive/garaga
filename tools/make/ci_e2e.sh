#!/bin/bash

source $(dirname "$0")/common.sh

run_ci_workflow ".github/workflows/e2e.yml"
