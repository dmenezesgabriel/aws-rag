resource "aws_s3_bucket" "frontend" {
  bucket = "${var.project_name}-frontend-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name        = "${var.project_name}-frontend"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

resource "aws_s3_bucket_policy" "frontend_public_read" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.frontend.arn}/*"
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

# Create config.js with the API endpoint
resource "aws_s3_object" "config_js" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "config.js"
  content_type = "application/javascript"
  content      = "window.API_ENDPOINT = '${aws_api_gateway_stage.api_stage.invoke_url}';"

  etag = md5("window.API_ENDPOINT = '${aws_api_gateway_stage.api_stage.invoke_url}';")
}

# Upload index.html with config.js included
resource "aws_s3_object" "index_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "index.html"
  content_type = "text/html"
  content = replace(
    file("${path.module}/../frontend/index.html"),
    "<div id=\"root\"></div>",
    "<script src=\"config.js\"></script>\n    <div id=\"root\"></div>"
  )

  etag = md5(replace(
    file("${path.module}/../frontend/index.html"),
    "<div id=\"root\"></div>",
    "<script src=\"config.js\"></script>\n    <div id=\"root\"></div>"
  ))
}

# Upload index.js as-is (no templating needed)
resource "aws_s3_object" "index_js" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "index.js"
  content_type = "application/javascript"
  source       = "${path.module}/../frontend/index.js"

  etag = filemd5("${path.module}/../frontend/index.js")
}

# Upload styles.css
resource "aws_s3_object" "styles_css" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "styles.css"
  content_type = "text/css"
  source       = "${path.module}/../frontend/styles.css"

  etag = filemd5("${path.module}/../frontend/styles.css")
}

output "frontend_url" {
  description = "URL of the S3-hosted frontend"
  value       = "http://${aws_s3_bucket.frontend.bucket}.s3-website-${var.aws_region}.amazonaws.com"
}

output "frontend_bucket" {
  description = "Name of the frontend S3 bucket"
  value       = aws_s3_bucket.frontend.bucket
}
