-- 물리 회전(Physical Baking) 후 규격 저장용.
-- AI 전처리에서 exif_transpose 적용 후 측정한 width/height를 저장.
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS width INTEGER;
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS height INTEGER;
