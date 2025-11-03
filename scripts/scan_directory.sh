#!/bin/bash

# --- Configuration ---
EXCLUDE_PATTERNS=(
  # Editor
  ".vscode"
  # Build
  "dist"
  #  Dependencies
  "node_modules"
  # Images
  ".jpeg"
  ".png"
  ".svg"
  ".avif"
  ".ico"
  # config files
  ".env"
  ".editorconfig"
  ".gitignore"
  ".angular"
  "angular.json"
  "package-lock.json"
  "tsconfig.json"
  "tsconfig.app.json"
  "tsconfig.spec.json"
  # Storybook
  ".storybook"
  "stories"
  ".stories.ts"
  # Tests
  ".spec.ts"
  ".test.ts"
  # Styles
  ".scss"
  # ".css"
  # Markdown
  # ".md"
  ".mdx"
  # ".ts"
  "documentation.json"
  "mockServiceWorker.js"
  "coverage"
  # Python
  ".mypy_cache"
  ".venv"
  "uv.lock"
  ".python-version"
  # Infra
  ".terraform"
  ".terraform.lock.hcl"
  "terraform.tfstate"
  "terraform.tfstate.backup"
  # Misc
  "Makefile"
  "scripts"
  ".gitignore"
  ".git"
  "app.assistant"
)

# --- Argument Validation ---
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <target_directory> <output_file>"
  exit 1
fi

TARGET_DIR="$1"
OUTPUT_FILE="$2"

# --- Main Script ---
> "$OUTPUT_FILE"

total_lines=0

# Use a 'while' loop with input redirection to keep the variable in the main shell.
while read -r file; do
  should_ignore=false

  for pattern in "${EXCLUDE_PATTERNS[@]}"; do
    if [[ "$file" == *"$pattern"* ]]; then
      should_ignore=true
      break
    fi
  done

  if [[ "$file" == *.ico || "$file" == *.editorconfig || "$file" == *.gitignore ]]; then
    should_ignore=true
  fi

  if [[ "$should_ignore" == false ]]; then
    relative_path=$(realpath --relative-to="$TARGET_DIR" "$file")

    file_lines=$(wc -l < "$file")
    total_lines=$((total_lines + file_lines))

    echo "--- $relative_path ($file_lines lines)" | tee -a "$OUTPUT_FILE"
    cat "$file" >> "$OUTPUT_FILE"
  fi
done < <(find "$TARGET_DIR" -type f)

# --- Final Summary ---
echo ""
echo "Process completed. The total number of lines is: $total_lines."
echo "The result was saved to '$TARGET_DIR' '$OUTPUT_FILE'."