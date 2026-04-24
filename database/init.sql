-- UUID support
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop existing tables if doing a clean restore (commented by default)
-- Uncomment these lines if you want to completely reset the database
-- DROP TABLE IF EXISTS feedback_logs CASCADE;
-- DROP TABLE IF EXISTS submissions CASCADE;
-- DROP TABLE IF EXISTS reference_images CASCADE;

-- Main submissions table (includes all migrations)
CREATE TABLE IF NOT EXISTS submissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id VARCHAR(100) UNIQUE NOT NULL,
    assign_id VARCHAR(200),
    student_id VARCHAR(64) NOT NULL,  -- SHA-256 hashed
    submission_url TEXT,
    submission_type VARCHAR(20),
    submission_text TEXT,
    status integer DEFAULT 0,
    retry_count integer DEFAULT 0,
    result jsonb,
    message text,
    phash VARCHAR(64),  -- perceptual hash
    dhash VARCHAR(64),  -- difference hash
    ahash VARCHAR(64),  -- average hash
    is_plagiarized BOOLEAN DEFAULT FALSE,
    similarity_score DECIMAL(5,4),  -- 0.0000 to 1.0000
    match_type VARCHAR(50),
    matched_reference_id UUID,
    processed_at TIMESTAMP,
    processing_time_ms INTEGER,
    clip_embedding_generated BOOLEAN DEFAULT FALSE,
    clip_embedding vector(768),  -- normalized CLIP embeddings (ViT-L/14)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    peer_plagiarism_detected BOOLEAN DEFAULT FALSE,
    matched_peer_submission_ids TEXT[],
	matched_reference_ids TEXT[],
    matched_reference_image_urls TEXT[] DEFAULT '{}',
    matched_peer_assign_ids TEXT[] DEFAULT '{}',
    matched_self_image_urls TEXT[] DEFAULT '{}',
    matched_peer_student_ids TEXT[] DEFAULT '{}',
    matched_peer_image_urls TEXT[] DEFAULT '{}',
    matched_peer_similarity_scores FLOAT[] DEFAULT '{}',
    self_plagiarism_detected BOOLEAN DEFAULT FALSE,
    matched_self_submission_ids TEXT[],
    resubmission_within_window BOOLEAN DEFAULT FALSE,
    days_since_last_submission INTEGER,
    plagiarism_source VARCHAR(50),
    is_ai_generated BOOLEAN DEFAULT FALSE,
    ai_detection_source VARCHAR(200),
    ai_confidence DECIMAL(5,4),
    CONSTRAINT valid_similarity_score CHECK (similarity_score >= 0 AND similarity_score <= 1),
    CONSTRAINT valid_ai_confidence CHECK (ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1))
);

-- Indexes for fast lookups
CREATE INDEX idx_submissions_submission_id ON submissions(submission_id);
CREATE INDEX idx_submissions_phash ON submissions(phash);  -- hash comparison
CREATE INDEX idx_submissions_dhash ON submissions(dhash);
CREATE INDEX idx_submissions_ahash ON submissions(ahash);
CREATE INDEX idx_submissions_student_created ON submissions(student_id, created_at DESC);  -- self-plagiarism
CREATE INDEX idx_submissions_is_ai_generated ON submissions(is_ai_generated);  -- AI detection queries

-- pgvector index for submission similarity search using inner product (faster for normalized vectors)
-- For normalized embeddings: inner_product = cosine_similarity
CREATE INDEX IF NOT EXISTS idx_submissions_clip_embedding 
ON submissions 
USING hnsw (clip_embedding vector_ip_ops);

-- Reference images corpus
CREATE TABLE IF NOT EXISTS reference_images (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reference_id VARCHAR(200) UNIQUE NOT NULL, -- will be used as assignment id when fetching references from assignments
    image_path TEXT NOT NULL,
    phash VARCHAR(64) NOT NULL,
    dhash VARCHAR(64) NOT NULL,
    ahash VARCHAR(64) NOT NULL,
    category VARCHAR(200),
    description TEXT,
    source VARCHAR(200),
    faiss_index_position INTEGER,
    clip_embedding_generated BOOLEAN DEFAULT FALSE,
    clip_embedding vector(768),  -- normalized CLIP embeddings (ViT-L/14)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for reference lookups
CREATE INDEX idx_reference_images_reference_id ON reference_images(reference_id);
CREATE INDEX idx_reference_images_phash ON reference_images(phash);
CREATE INDEX idx_reference_images_dhash ON reference_images(dhash);
CREATE INDEX idx_reference_images_ahash ON reference_images(ahash);
CREATE INDEX idx_reference_images_faiss_position ON reference_images(faiss_index_position);

-- pgvector index for inner product search (HNSW - Hierarchical Navigable Small World)
-- For normalized embeddings: inner_product = cosine_similarity (faster than cosine_ops)
CREATE INDEX IF NOT EXISTS idx_reference_images_clip_embedding 
ON reference_images 
USING hnsw (clip_embedding vector_ip_ops);

-- LLM feedback tracking
CREATE TABLE IF NOT EXISTS feedback_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id UUID NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    llm_provider VARCHAR(50) NOT NULL,
    llm_model VARCHAR(100) NOT NULL,
    feedback_text TEXT NOT NULL,
    prompt_used TEXT,
    generation_time_ms INTEGER,
    tokens_used INTEGER,
    sent_to_glific BOOLEAN DEFAULT FALSE,
    glific_message_id VARCHAR(100),
    delivery_status VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    delivered_at TIMESTAMP
);

-- Feedback indexes
CREATE INDEX idx_feedback_logs_submission_id ON feedback_logs(submission_id);

-- Calculate bit differences between hashes
CREATE OR REPLACE FUNCTION hamming_distance(hash1 VARCHAR, hash2 VARCHAR)
RETURNS INTEGER AS $$
DECLARE
    distance INTEGER := 0;
    i INTEGER;
    byte1 INTEGER;
    byte2 INTEGER;
BEGIN
    IF LENGTH(hash1) != LENGTH(hash2) THEN
        RETURN 999;  -- invalid
    END IF;
    
    -- compare each hex digit
    FOR i IN 1..LENGTH(hash1) LOOP
        byte1 := ('x' || SUBSTRING(hash1, i, 1))::bit(4)::integer;
        byte2 := ('x' || SUBSTRING(hash2, i, 1))::bit(4)::integer;
        distance := distance + BIT_COUNT((byte1 # byte2)::bit(4));
    END LOOP;
    
    RETURN distance;
END;
$$ LANGUAGE plpgsql IMMUTABLE;