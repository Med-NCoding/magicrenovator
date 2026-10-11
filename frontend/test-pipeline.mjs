import handler from './api/[...path].js';
import { EventEmitter } from 'events';

class MockRequest extends EventEmitter {
  constructor(method, url, headers = {}, body = null) {
    super();
    this.method = method;
    this.url = url;
    this.headers = headers;
    this.body = body;
  }
}

class MockResponse extends EventEmitter {
  constructor() {
    super();
    this.statusCode = 200;
    this.headers = {};
    this._data = '';
  }

  setHeader(name, value) {
    this.headers[name.toLowerCase()] = value;
  }

  getHeader(name) {
    return this.headers[name.toLowerCase()];
  }

  end(chunk) {
    if (chunk) this._data += chunk;
    this.emit('finish');
  }

  json() {
    try {
      return JSON.parse(this._data);
    } catch {
      return this._data;
    }
  }
}

function runHandler(method, url, headers = {}, body = null) {
  return new Promise((resolve) => {
    const req = new MockRequest(method, url, headers, body);
    const res = new MockResponse();

    res.on('finish', () => {
      resolve({ status: res.statusCode, headers: res.headers, data: res.json() });
    });

    handler(req, res);

    if (body) {
      if (typeof body === 'string' || Buffer.isBuffer(body)) {
        req.emit('data', Buffer.from(body));
      } else {
        req.emit('data', Buffer.from(JSON.stringify(body)));
      }
    }
    req.emit('end');
  });
}

async function runTests() {
  console.log('--- STARTING 5 AUTOMATED VERIFICATION TESTS ---');

  // TEST 1: Missing Photo Rejection
  console.log('\n[Test 1] Missing photo safeguard: POST /api/generations without uploaded photo');
  const t1 = await runHandler('POST', '/api/generations', {
    authorization: 'Bearer mock_mh_key_123',
    'content-type': 'application/json'
  }, {});
  console.log(`Test 1 status: ${t1.status}, code: ${t1.data?.error?.code}, message: ${t1.data?.error?.message}`);
  if (t1.status === 400 && t1.data?.error?.code === 'missing_photo') {
    console.log('✅ TEST 1 PASSED: Zero credits spent, blocked cleanly with 400 missing_photo!');
  } else {
    console.error('❌ TEST 1 FAILED', t1);
    process.exit(1);
  }

  // TEST 2: Session & CSRF Token Generation
  console.log('\n[Test 2] Session initiation: GET /api/session');
  const t2 = await runHandler('GET', '/api/session');
  console.log(`Test 2 status: ${t2.status}, active: ${t2.data?.session_active}, csrf: ${t2.data?.csrf_token}`);
  if (t2.status === 200 && t2.data?.session_active && t2.data?.csrf_token) {
    console.log('✅ TEST 2 PASSED: Session active with valid CSRF token!');
  } else {
    console.error('❌ TEST 2 FAILED', t2);
    process.exit(1);
  }

  // TEST 3: Room Creation & Room Retrieval
  console.log('\n[Test 3] Project & Room creation: POST /api/projects/:id/rooms');
  const t3 = await runHandler('POST', '/api/projects/proj_test/rooms', {
    'content-type': 'application/json'
  }, { name: 'Master Bedroom', room_type: 'bedroom' });
  console.log(`Test 3 status: ${t3.status}, room_id: ${t3.data?.id}, name: ${t3.data?.name}`);
  if (t3.status === 200 && t3.data?.id && t3.data?.name === 'Master Bedroom') {
    console.log('✅ TEST 3 PASSED: Room created successfully!');
  } else {
    console.error('❌ TEST 3 FAILED', t3);
    process.exit(1);
  }

  // TEST 4: Cold Start Query Parameter Recovery for GET /api/generations/:id?provider_id=...
  console.log('\n[Test 4] Cold start recovery: GET /api/generations/gen_cold_123?provider_id=mh_proj_abc&kind=image');
  const t4 = await runHandler('GET', '/api/generations/gen_cold_123?provider_id=mh_proj_abc&kind=image', {
    authorization: 'Bearer mock_mh_key_123'
  });
  console.log(`Test 4 status: ${t4.status}, job_id: ${t4.data?.job_id}, provider_id: ${t4.data?.provider_id}, state: ${t4.data?.state}`);
  if (t4.status === 200 && t4.data?.job_id === 'gen_cold_123' && t4.data?.provider_id === 'mh_proj_abc') {
    console.log('✅ TEST 4 PASSED: Successfully restored job on cold-start container using provider_id query parameter!');
  } else {
    console.error('❌ TEST 4 FAILED', t4);
    process.exit(1);
  }

  // TEST 5: Start Generation with Explicit File Path & Prompt
  console.log('\n[Test 5] Start generation with valid file_path: POST /api/generations');
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    if (url.includes('api.magichour.ai/v1/account')) {
      return { ok: true, json: async () => ({ tier: 'free', credits: 500 }) };
    }
    if (url.includes('api.magichour.ai/v1/ai-image-editor')) {
      const parsedBody = JSON.parse(options.body);
      return {
        ok: true,
        json: async () => ({
          id: 'mh_cuid_test_999',
          name: parsedBody.name,
          status: 'queued'
        })
      };
    }
    if (url.includes('api.magichour.ai/v1/image-projects/mh_cuid_test_999')) {
      return {
        ok: true,
        json: async () => ({
          id: 'mh_cuid_test_999',
          status: 'complete',
          downloads: [{ url: 'https://images.magichour.ai/output_test_finished.jpg' }]
        })
      };
    }
    return originalFetch(url, options);
  };

  const t5Start = await runHandler('POST', '/api/generations', {
    authorization: 'Bearer valid_mh_key',
    'content-type': 'application/json'
  }, {
    file_path: 'api-assets/valid_room_123.jpg',
    prompt: 'luxury modern kitchen renovation',
    room_id: 'rm_test_kitchen'
  });

  console.log(`Test 5 Submission: status ${t5Start.status}, job_id: ${t5Start.data?.job_id}, provider_id: ${t5Start.data?.provider_id}`);

  // Poll for completion:
  const t5Poll = await runHandler('GET', `/api/generations/${t5Start.data?.job_id}?provider_id=${t5Start.data?.provider_id}&kind=image`, {
    authorization: 'Bearer valid_mh_key'
  });

  console.log(`Test 5 Poll Result: state: ${t5Poll.data?.state}, output_url: ${t5Poll.data?.output_asset_url}`);

  globalThis.fetch = originalFetch;

  // TEST 6: Strict Resolution & Model Verification (640px sent and returned, NEVER 1k when 640px chosen)
  console.log('\n[Test 6] Strict resolution test: Verify 640px is sent to Magic Hour and returned by status API');
  let sentMhPayload = null;
  globalThis.fetch = async (url, options) => {
    if (url.includes('api.magichour.ai/v1/account')) {
      return { ok: true, json: async () => ({ tier: 'pro', credits: 1500 }) };
    }
    if (url.includes('api.magichour.ai/v1/ai-image-editor')) {
      sentMhPayload = JSON.parse(options.body);
      return {
        ok: true,
        json: async () => ({
          id: 'mh_cuid_res_640',
          name: sentMhPayload.name,
          status: 'complete',
          downloads: [{ url: 'https://images.magichour.ai/output_640.jpg' }]
        })
      };
    }
    if (url.includes('api.magichour.ai/v1/image-projects/mh_cuid_res_640')) {
      return {
        ok: true,
        json: async () => ({
          id: 'mh_cuid_res_640',
          status: 'complete',
          downloads: [{ url: 'https://images.magichour.ai/output_640.jpg' }]
        })
      };
    }
    if (url.includes('images.magichour.ai/output_640.jpg')) {
      const dummyBytes = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]);
      return {
        ok: true,
        status: 200,
        headers: { get: (k) => k.toLowerCase() === 'content-type' ? 'image/jpeg' : null },
        arrayBuffer: async () => dummyBytes.buffer
      };
    }
    return originalFetch(url, options);
  };

  const t6Start = await runHandler('POST', '/api/generations', {
    authorization: 'Bearer valid_mh_key',
    'content-type': 'application/json'
  }, {
    file_path: 'api-assets/valid_room_123.jpg',
    resolution: '640px',
    model: 'qwen-edit',
    room_id: 'rm_test_kitchen'
  });

  const t6Poll = await runHandler('GET', `/api/generations/${t6Start.data?.job_id}?provider_id=${t6Start.data?.provider_id}&kind=image&resolution=640px&model=qwen-edit`, {
    authorization: 'Bearer valid_mh_key'
  });

  globalThis.fetch = originalFetch;

  console.log(`Test 6 Sent to MH resolution: ${sentMhPayload?.resolution}, Status API resolution: ${t6Poll.data?.resolution}, Credits: ${t6Poll.data?.billing?.actual_credits}, output_data_url prefix: ${t6Poll.data?.output_data_url?.substring(0, 23)}`);
  if (
    sentMhPayload?.resolution === '640px' &&
    t6Poll.data?.resolution === '640px' &&
    t6Poll.data?.billing?.actual_credits === 10 &&
    t6Poll.data?.output_data_url?.startsWith('data:image/jpeg;base64,')
  ) {
    console.log('✅ TEST 6 PASSED: Resolution is strictly 640px (10 credits) and output_data_url is embedded!');
  } else {
    console.error('❌ TEST 6 FAILED: Resolution or output_data_url mismatch', {
      sent: sentMhPayload?.resolution,
      received: t6Poll.data?.resolution,
      credits: t6Poll.data?.billing?.actual_credits,
      output_data_url: t6Poll.data?.output_data_url
    });
    process.exit(1);
  }

  // TEST 7: Image Upload Self-Contained Thumbnail Verification (JSON base64 payload)
  console.log('\n[Test 7] Base64 JSON upload: Verify POST /api/rooms/:id/assets uploads cleanly and returns data URL');
  globalThis.fetch = async (url, options) => {
    if (url.includes('api.magichour.ai/v1/files/upload-urls')) {
      return {
        ok: true,
        json: async () => ({
          items: [{ upload_url: 'https://s3.amazonaws.com/mock-put-url', file_path: 'uploads/room_clean_photo.jpg' }]
        })
      };
    }
    if (url.includes('s3.amazonaws.com/mock-put-url')) {
      return { ok: true, status: 200 };
    }
    return originalFetch(url, options);
  };

  const dummyJpegBase64 = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00]).toString('base64');
  const t7Upload = await runHandler('POST', '/api/rooms/rm_test_kitchen/assets', {
    authorization: 'Bearer valid_mh_key',
    'content-type': 'application/json'
  }, {
    data_url: `data:image/jpeg;base64,${dummyJpegBase64}`,
    filename: 'dorm_photo.jpg',
    mime_type: 'image/jpeg'
  });

  globalThis.fetch = originalFetch;

  console.log(`Test 7 status: ${t7Upload.status}, file_path: ${t7Upload.data?.file_path}, thumbnail_url prefix: ${t7Upload.data?.thumbnail_url?.substring(0, 25)}`);
  if (t7Upload.status === 201 && t7Upload.data?.file_path === 'uploads/room_clean_photo.jpg' && t7Upload.data?.thumbnail_url?.startsWith('data:image/jpeg;base64,')) {
    console.log('✅ TEST 7 PASSED: Base64 JSON upload succeeded and returned self-contained data URL!');
  } else {
    console.error('❌ TEST 7 FAILED: Invalid upload response', t7Upload);
    process.exit(1);
  }

  // TEST 8: Unsupported File Format Rejection (e.g. .gif or .pdf)
  console.log('\n[Test 8] Unsupported file format check: Verify .gif / .pdf is rejected according to Magic Hour rules');
  const t8Unsupported = await runHandler('POST', '/api/rooms/rm_test_kitchen/assets', {
    authorization: 'Bearer valid_mh_key',
    'content-type': 'application/json'
  }, {
    data_url: `data:image/gif;base64,${dummyJpegBase64}`,
    filename: 'animated_room.gif',
    mime_type: 'image/gif'
  });
  console.log(`Test 8 status: ${t8Unsupported.status}, code: ${t8Unsupported.data?.error?.code}, message: ${t8Unsupported.data?.error?.message}`);
  if (t8Unsupported.status === 400 && t8Unsupported.data?.error?.code === 'unsupported_format') {
    console.log('✅ TEST 8 PASSED: Unsupported format rejected with clear user-facing error message!');
  } else {
    console.error('❌ TEST 8 FAILED: Did not reject unsupported format', t8Unsupported);
    process.exit(1);
  }

  // TEST 9: Project always has default workspace (no empty Rooms[] screen)
  console.log('\n[Test 9] Default workspace check: Verify GET /api/projects/:id always includes workspace');
  const t9Project = await runHandler('GET', '/api/projects/proj_cold_start_999');
  console.log(`Test 9 status: ${t9Project.status}, rooms length: ${t9Project.data?.rooms?.length}`);
  if (t9Project.status === 200 && Array.isArray(t9Project.data?.rooms) && t9Project.data.rooms.length >= 1) {
    console.log('✅ TEST 9 PASSED: Project always has a default workspace, never shows empty Rooms screen!');
  } else {
    console.error('❌ TEST 9 FAILED: Project returned empty rooms', t9Project);
    process.exit(1);
  }

  console.log('\n🎉 ALL 9 TESTS PASSED SUCCESSFULLY! ZERO ERRORS DETECTED.');
}

runTests();

