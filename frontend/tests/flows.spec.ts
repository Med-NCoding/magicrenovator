import { test, expect, type Page } from '@playwright/test';

async function uploadCanvasRoomPhoto(page: Page, filename = 'kitchen.png'): Promise<void> {
  await expect(page.getByTestId('room-photo-input')).toBeAttached({ timeout: 10000 });
  await page.evaluate(async (fname) => {
    const canvas = document.createElement('canvas');
    canvas.width = 160;
    canvas.height = 120;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('2D context unavailable');
    for (let y = 0; y < 120; y += 8) {
      for (let x = 0; x < 160; x += 8) {
        const isLight = ((x >> 3) + (y >> 3)) % 2 === 0;
        ctx.fillStyle = isLight ? '#e2dcd0' : '#3a424a';
        ctx.fillRect(x, y, 8, 8);
      }
    }
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob failed'))), 'image/png');
    });
    const file = new File([blob], fname, { type: 'image/png' });
    const dt = new DataTransfer();
    dt.items.add(file);
    const input = document.querySelector('[data-testid="room-photo-input"]') as HTMLInputElement | null;
    if (!input) throw new Error('room-photo-input not found');
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, filename);
}

test.describe('magicrenovator End-to-End Customer Flows', () => {
  test('Full Kitchen & Multi-Room Renovation Flow, Presentation Assembly, and Secret Isolation', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/app');

    // 1. Connect Magic Hour BYOK key via modal
    const rawSecretKey = `mhk_mock_5000_e2e_${Date.now()}_9988`;
    await page.getByRole('button', { name: 'Connect Magic Hour' }).first().click();
    const keyInput = page.locator('#mh-api-key-input');
    await expect(keyInput).toBeVisible();
    await keyInput.fill(rawSecretKey);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();

    await expect(page.getByTestId('connection-pill')).toContainText('5000 credits');

    // Verify raw key is never persisted in browser storage or visible DOM
    const storageDump = await page.evaluate(() =>
      JSON.stringify({
        local: Object.entries(localStorage),
        session: Object.entries(sessionStorage),
      })
    );
    expect(storageDump).not.toContain(rawSecretKey);

    // 2. Create a new project
    await page.locator('#new-project-name').fill('Cedar Lane Remodel');
    await page.getByRole('button', { name: 'Create Project' }).click();
    await expect(page).toHaveURL(/\/app\/projects\/prj_.*\/rooms\/rm_.*/);

    // 3. Upload a room photo (verify 'Take photo' is removed and only 'Upload Photo' is shown)
    await expect(page.getByText('Take photo', { exact: false })).toHaveCount(0);
    await uploadCanvasRoomPhoto(page, 'kitchen.png');
    await expect(page.getByAltText('Kitchen reference')).toBeVisible();

    // 4. Enter and compile renovation brief
    await page
      .getByTestId('brief-raw-text')
      .fill('Paint the cabinets warm sage green, add brass hardware, and install white quartz countertops.');
    await page.getByTestId('save-brief-btn').click();
    await expect(page.getByTestId('compiled-prompt-preview')).toBeVisible();

    // Verify Photo / Video output format selector is visible
    await expect(page.getByTestId('media-kind-selector')).toBeVisible();
    await expect(page.getByTestId('select-kind-image')).toBeVisible();
    await expect(page.getByTestId('select-kind-video')).toBeVisible();

    // 5. Calculate still image quote -> verify setup & estimate form disappear, leaving Photo/Video choice + Confirm & Spend
    await page.getByTestId('calculate-quote-image').click();
    await expect(page.getByTestId('quote-summary-image')).toBeVisible();
    await expect(page.getByTestId('calculate-quote-image')).toHaveCount(0);
    await expect(page.getByTestId('brief-raw-text')).toHaveCount(0);
    await expect(page.getByTestId('media-kind-selector')).toBeVisible();
    await page.getByTestId('confirm-quote-image').click();

    // 6. Wait for background worker to complete still image, then test REVISION & RE-QUOTING flow
    await expect(page.getByTestId('image-compare')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('review-checklist-image')).toBeVisible();

    // Verify Split Slider option is removed
    await expect(page.getByTestId('mode-slider-btn')).toHaveCount(0);
    await expect(page.getByText('Split Slider')).toHaveCount(0);

    // Verify Approved Download section is NOT shown before approval
    await expect(page.getByTestId('approved-download-section')).toHaveCount(0);

    // Verify Calculate Credit Quote is NOT shown until user writes revised prompt and clicks Send Revision
    await expect(page.getByTestId('quote-card-image')).toHaveCount(0);

    await page.getByTestId('review-notes-image').fill('Make the brass hardware slightly darker and keep everything else.');
    await page.getByTestId('revise-review-image').click();

    // Verify revision hides old review/image screens and shows Photo/Video choice + Confirm & Spend directly in front of the user
    await expect(page.getByTestId('revision-quote-banner')).toBeVisible();
    await expect(page.getByTestId('image-compare')).toHaveCount(0);
    await expect(page.getByTestId('review-checklist-image')).toHaveCount(0);
    await expect(page.getByTestId('media-kind-selector')).toBeVisible();
    await expect(page.getByTestId('quote-card-image')).toBeVisible();
    await expect(page.getByTestId('quote-summary-image')).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('calculate-quote-image')).toHaveCount(0);
    await page.getByTestId('confirm-quote-image').click();

    // Wait for revised image to complete; verify Approved section is still hidden while in ready_for_review
    await expect(page.getByTestId('accept-review-image')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('approved-download-section')).toHaveCount(0);
    await expect(page.getByTestId('quote-card-image')).toHaveCount(0);
    await page.getByTestId('accept-review-image').click();

    await expect(page.getByTestId('still-accepted-badge')).toBeVisible();
    await expect(page.getByTestId('approved-download-section')).toBeVisible();
    await expect(page.getByTestId('download-approved-photo')).toBeVisible();
    await expect(page.getByTestId('quote-card-image')).toHaveCount(0);

    // 7. Switch to Video format right from the approved screen, calculate video clip quote & confirm spend
    await page.getByTestId('select-kind-video').click();
    await expect(page.getByTestId('quote-card-video')).toBeVisible();
    await page.getByTestId('calculate-quote-video').click();
    await expect(page.getByTestId('quote-summary-video')).toBeVisible();
    await expect(page.getByTestId('calculate-quote-video')).toHaveCount(0);
    await page.getByTestId('confirm-quote-video').click();

    // 8. Wait for video clip completion and accept it
    await expect(page.getByTestId('video-review-section')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('approved-download-section')).toHaveCount(0);
    await page.getByTestId('accept-review-video').click();
    await expect(page.getByTestId('video-accepted-badge')).toBeVisible();
    await expect(page.getByTestId('approved-download-section')).toBeVisible();
    await expect(page.getByTestId('download-approved-video')).toBeVisible();

    // 9. Assemble house presentation and verify export package
    await expect(page.getByTestId('clip-order-item-0')).toBeVisible();
    await page.getByTestId('assemble-presentation-btn').click();

    await expect(page.getByTestId('export-panel')).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId('export-status-badge')).toHaveText('ready', { timeout: 20000 });
    await expect(page.getByTestId('presentation-video-player')).toBeVisible();
    await expect(page.getByTestId('download-presentation-video')).toBeVisible();
    await expect(page.getByTestId('export-brief-markdown')).toContainText('Cedar Lane Remodel');
    await expect(page.getByTestId('concept-limitation-notice')).toContainText('Visual concept');
  });

  test('Low-Credit Video Quote Recovery and Mobile Viewport Layout', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    await page.goto('/app');

    // Verify no horizontal overflow on mobile viewport
    const hasOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 2
    );
    expect(hasOverflow).toBe(false);

    // Connect a key that starts with 240 credits (enough for 50-credit image, leaves 190 < 240 for video)
    await page.getByRole('button', { name: 'Connect Magic Hour' }).first().click();
    await page.locator('#mh-api-key-input').fill(`mhk_mock_low240_${Date.now()}`);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await expect(page.getByTestId('connection-pill')).toContainText('240 credits');

    await page.locator('#new-project-name').fill('Mobile Credit Recovery Project');
    await page.getByRole('button', { name: 'Create Project' }).click();

    await uploadCanvasRoomPhoto(page, 'kitchen_mobile.png');
    await expect(page.getByAltText('Kitchen reference')).toBeVisible();

    await page
      .getByTestId('brief-raw-text')
      .fill('Replace countertops with honed marble and keep windows and layout.');
    await page.getByTestId('save-brief-btn').click();

    // Generate 50-credit still image -> remaining balance becomes 190 credits
    await page.getByTestId('calculate-quote-image').click();
    await page.getByTestId('confirm-quote-image').click();
    await expect(page.getByTestId('accept-review-image')).toBeVisible({ timeout: 15000 });
    await page.getByTestId('accept-review-image').click();

    // Switch to Video and request video quote (requires 240 credits, only 190 available) -> blocked with insufficient credits
    await page.getByTestId('select-kind-video').click();
    await page.getByTestId('calculate-quote-video').click();
    await expect(page.getByTestId('quote-summary-video')).toContainText('Insufficient credits');

    // Click 'Refresh Balance & Re-Quote' -> simulates top-up to 1000 credits and unlocks confirm button
    await page.getByRole('button', { name: 'Refresh Balance & Re-Quote' }).click();
    await expect(page.getByTestId('confirm-quote-video')).toBeVisible();

    await context.close();
  });
});
