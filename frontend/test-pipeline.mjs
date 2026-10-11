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

  if (
    t5Start.status === 200 &&
    t5Start.data?.provider_id === 'mh_cuid_test_999' &&
    t5Poll.data?.state === 'ready_for_review' &&
    t5Poll.data?.output_asset_url === 'https://images.magichour.ai/output_test_finished.jpg'
  ) {
    console.log('✅ TEST 5 PASSED: Full end-to-end generation lifecycle from queue to completion verified!');
  } else {
    console.error('❌ TEST 5 FAILED', { t5Start, t5Poll });
    process.exit(1);
  }

  console.log('\n🎉 ALL 5 TESTS PASSED SUCCESSFULLY! ZERO ERRORS DETECTED.');
}

runTests();
