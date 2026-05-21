-- Migration: Rename image_url to submission_url and add submission_type, submission_text
ALTER TABLE submissions RENAME COLUMN image_url TO submission_url;
ALTER TABLE submissions ADD COLUMN submission_type VARCHAR(20);
ALTER TABLE submissions ADD COLUMN submission_text TEXT;