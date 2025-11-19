#!/bin/bash

# submission_runner.sh
# ----------------------------------------------------------
# Usage:
#   ./submission_runner.sh <alias> [options]
#
# Aliases:
#   ns   - New Submission
#   re   - Resubmission
#   ci   - Corpus Image
#   si   - Stock Image
#   sim  - Stock Image Modified
#   ps   - Peer Submission
#   ai   - AI Generated
#   c    - Custom Submission (requires student_id, assignment_id, image_url)
#   gr   - Get Results (requires student_id)
#
# Examples:
#   ./submission_runner.sh ns
#   ./submission_runner.sh c ST1 assignment-demo https://example.com/image.jpg
#   ./submission_runner.sh gr ST2
# ----------------------------------------------------------

alias_input="$1"
URL="http://localhost:8000/api/v1"
HEADER="content-type: application/json"

if [ -z "$alias_input" ]; then
  echo "Usage: $0 <alias> [options]"
  echo ""
  echo "Aliases:"
  echo "  ns   - New Submission"
  echo "  re   - Resubmission"
  echo "  ci   - Corpus Image"
  echo "  si   - Stock Image"
  echo "  sim  - Stock Image Modified"
  echo "  ps   - Peer Submission"
  echo "  ai   - AI Generated"
  echo "  c    - Custom Submission (requires student_id, assignment_id, image_url)"
  echo "  gr   - Get Results (requires student_id)"
  exit 1
fi

case "$alias_input" in
  ns)
    scenario="New Submission"
    endpoint="$URL/submissions"
    method="POST"
    data='{"student_id":"ST1","assignment_id":"assignment-sub","image_url":"https://i.pinimg.com/originals/4d/d0/a0/4dd0a07570b00a7bcc1ec84fbc2fce9e.jpg"}'
    ;;
  re)
    scenario="Resubmission"
    endpoint="$URL/submissions"
    method="POST"
    data='{"student_id":"ST1","assignment_id":"assignment-sub","image_url":"https://i.pinimg.com/originals/4d/d0/a0/4dd0a07570b00a7bcc1ec84fbc2fce9e.jpg"}'
    ;;
  ci)
    scenario="Corpus Image"
    endpoint="$URL/submissions"
    method="POST"
    data='{"student_id":"ST1","assignment_id":"assignment-1-corpus-image","image_url":"https://storage.googleapis.com/bucket_tap_1/uploads/added_in_coll/20250618012600_C1250843_F22057_M13076613.png"}'
    ;;
  si)
    scenario="Stock Image"
    endpoint="$URL/submissions"
    method="POST"
    data='{"student_id":"ST1","assignment_id":"assignment-stock-image","image_url":"https://images.pexels.com/photos/145901/pexels-photo-145901.jpeg"}'
    ;;
  sim)
    scenario="Stock Image Modified"
    endpoint="$URL/submissions"
    method="POST"
    data='{"student_id":"ST1","assignment_id":"assignment-stock-image-mod","image_url":"https://amadeusaichatbot.blob.core.windows.net/docbot-container/animal-dup.jpeg"}'
    ;;
  ps)
    scenario="Peer Submission"
    endpoint="$URL/submissions"
    method="POST"
    data='{"student_id":"ST2","assignment_id":"assignment-peer","image_url":"https://i.pinimg.com/originals/4d/d0/a0/4dd0a07570b00a7bcc1ec84fbc2fce9e.jpg"}'
    ;;
  ai)
    scenario="AI Generated"
    endpoint="$URL/submissions"
    method="POST"
    data='{"student_id":"ST1","assignment_id":"assignment-ai","image_url":"https://amadeusaichatbot.blob.core.windows.net/docbot-container/ChatGPT%20Image%20Nov%206,%202025,%2009_42_48%20AM.png"}'
    ;;
  c)
    if [ $# -ne 4 ]; then
      echo "Error: Custom mode requires 3 arguments."
      echo "Usage: $0 c <student_id> <assignment_id> <image_url>"
      exit 1
    fi
    scenario="Custom Submission"
    endpoint="$URL/submissions"
    method="POST"
    student_id="$2"
    assignment_id="$3"
    image_url="$4"
    data="{\"student_id\":\"$student_id\",\"assignment_id\":\"$assignment_id\",\"image_url\":\"$image_url\"}"
    ;;
  gr)
    if [ $# -ne 2 ]; then
      echo "Error: Get Results requires student_id."
      echo "Usage: $0 gr <student_id>"
      exit 1
    fi
    student_id="$2"
    scenario="Get Results for Student $student_id"
    endpoint="$URL/results/$student_id"
    method="GET"
    ;;
  *)
    echo "Invalid alias: $alias_input"
    echo "Run '$0' with no arguments to see available options."
    exit 1
    ;;
esac

# Display scenario info
echo "==============================="
echo "Scenario: $scenario"
echo "==============================="
echo "$method $endpoint"
echo ""

# Execute appropriate curl request
if [ "$method" = "POST" ]; then
  response=$(curl -s -X POST "$endpoint" -H "$HEADER" -d "$data")
else
  response=$(curl -s -X GET "$endpoint" -H "$HEADER")
fi

# Pretty print the JSON response if jq is available
if command -v jq &> /dev/null; then
  echo "Response:"
  echo "$response" | jq
else
  echo "Response (raw):"
  echo "$response"
fi

echo "==============================="
