# Magic Hour Official API Reference & Reviewed Catalog

- **Reviewed Date**: 2026-10-03
- **Selected OpenAPI Schema Version**: `3.0.2` (`Magic Hour API beta`)
- **Catalog Version**: `mh-catalog-2026-10-03-v1`
- **Base URL**: `https://api.magichour.ai/v1`

## Official Endpoint Links
1. **API Keys**: https://magichour.ai/developer?tab=api-keys
2. **Account Details (`GET /v1/account`)**: https://docs.magichour.ai/api-reference/account/get-account-details
3. **Upload URLs (`POST /v1/files/upload-urls`)**: https://docs.magichour.ai/api-reference/files/generate-asset-upload-urls
4. **AI Image Editor (`POST /v1/ai-image-editor`)**: https://docs.magichour.ai/api-reference/image-projects/ai-image-editor
5. **Get Image Details (`GET /v1/image-projects/{id}`)**: https://docs.magichour.ai/api-reference/image-projects/get-image-details
6. **Image-to-Video (`POST /v1/image-to-video`)**: https://docs.magichour.ai/api-reference/video-projects/image-to-video
7. **Get Video Details (`GET /v1/video-projects/{id}`)**: https://docs.magichour.ai/api-reference/video-projects/get-video-details
8. **Models and Credits**: https://docs.magichour.ai/api-reference/models
9. **Credit Purchase & Billing**: https://magichour.ai/pricing and https://docs.magichour.ai/billing/overview
10. **Inputs and Outputs Handling**: https://docs.magichour.ai/integration/inputs-and-outputs

## Recorded REST Field Contracts (Snake Case)
- **`GET /v1/account`** -> `{ "id": "string", "email": "string|null", "tier": "free|creator|pro|business", "credits": 500, "subscription": {...} }`
- **`POST /v1/files/upload-urls`** -> Request: `{ "items": [{ "type": "image", "extension": "png" }] }` -> Response: `{ "items": [{ "upload_url": "...", "expires_at": "...", "file_path": "api-assets/..." }] }`
- **`POST /v1/ai-image-editor`** -> Request: `{ "name": "...", "image_count": 1, "model": "seedream-v4.5", "resolution": "1k", "style": { "prompt": "..." }, "assets": { "image_file_paths": ["api-assets/..."] } }` -> Response: `{ "id": "...", "credits_charged": 50 }`
- **`GET /v1/image-projects/{id}`** -> Response: `{ "id": "...", "name": "...", "status": "queued|rendering|complete|error|canceled", "image_count": 1, "type": "AI_IMAGE_EDITOR", "created_at": "...", "enabled": true, "credits_charged": 50, "downloads": [{ "url": "...", "expires_at": "..." }], "error": null }`
- **`POST /v1/image-to-video`** -> Request: `{ "name": "...", "end_seconds": 5, "model": "ltx-2.5", "resolution": "720p", "audio": false, "style": { "prompt": "..." }, "assets": { "image_file_path": "api-assets/..." } }` -> Response: `{ "id": "...", "credits_charged": 240 }`
- **`GET /v1/video-projects/{id}`** -> Response: `{ "id": "...", "name": "...", "status": "queued|rendering|complete|error|canceled", "type": "IMAGE_TO_VIDEO", "created_at": "...", "width": 1280, "height": 720, "enabled": true, "start_seconds": 0, "end_seconds": 5, "credits_charged": 240, "fps": 30, "downloads": [{ "url": "...", "expires_at": "..." }], "error": null }`
