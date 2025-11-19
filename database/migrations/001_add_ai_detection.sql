-- Migration: Add AI-Generated Image Detection Support
-- Date: 2025-11-02

-- Add columns for AI-generated image detection
ALTER TABLE submissions 
ADD COLUMN IF NOT EXISTS is_ai_generated BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS ai_detection_source VARCHAR(200),
ADD COLUMN IF NOT EXISTS ai_confidence DECIMAL(5,4) CHECK (ai_confidence >= 0 AND ai_confidence <= 1);

-- Add index for AI-generated queries
CREATE INDEX IF NOT EXISTS idx_submissions_ai_generated ON submissions(is_ai_generated) WHERE is_ai_generated = TRUE;

-- Comment the columns
COMMENT ON COLUMN submissions.is_ai_generated IS 'True if image was detected as AI-generated (DALL-E, Midjourney, etc.)';
COMMENT ON COLUMN submissions.ai_detection_source IS 'Detection method or AI platform detected (e.g., "Metadata: DALL-E", "Statistical: GAN fingerprint")';
COMMENT ON COLUMN submissions.ai_confidence IS 'Confidence score 0.0-1.0 for AI detection';
