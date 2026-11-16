-- Chỉ mount vào PostgreSQL test tmpfs; runner chỉ đọc marker trước lifecycle DB.
COMMENT ON DATABASE bluedrive_test_control IS 'BlueDrive isolated regression control v1';
