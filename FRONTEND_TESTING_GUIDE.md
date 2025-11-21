# Frontend Testing Guide: PR5 Fallback Banners

This guide explains how to test the new fallback warning banners in the Factory Simulator UI.

## Prerequisites

1. Backend server running: `python -m backend.server`
2. Frontend dev server running: `npm run dev` (in `frontend/` directory)
3. Browser open to `http://localhost:5173/`

## Test Case 1: Successful Onboarding (No Banner)

**Objective:** Verify that when onboarding succeeds with 100% coverage, no fallback banner appears.

### Steps

1. Enter the default factory description (it should already be in the left textarea)
2. Enter any situation text in the right textarea
3. Click "Simulate"
4. Wait for results to load

### Expected Result

- Results appear in three panels: "Inferred Factory", "Scenarios & Metrics", "Decision Briefing"
- **NO yellow/amber warning banner** in the factory panel
- **NO blue notice** in the scenarios panel
- Meta shows `used_default_factory: false` (you can check in browser DevTools → Network → simulate response)

### Verification

Open browser DevTools → Network tab, click the simulate request, look at the Response:
```json
{
  "factory": {...},
  "specs": [...],
  "metrics": [...],
  "briefing": "...",
  "meta": {
    "used_default_factory": false,
    "onboarding_errors": [],
    "inferred_assumptions": []
  }
}
```

---

## Test Case 2: Fallback with Coverage Mismatch (Banner Visible)

**Objective:** Verify that when onboarding fails due to coverage mismatch, the fallback banner displays clearly.

### Steps

1. Clear the factory description textarea and enter intentionally unparseable text:
   ```
   We have machines X, Y, Z (not following ID grammar).
   We make products with unclear routing.
   This is deliberately broken to trigger fallback.
   ```

2. Enter any situation text
3. Click "Simulate"
4. Wait for results to load

### Expected Result

- Results appear (using the toy factory, M1/M2/M3, J1/J2/J3)
- **Yellow/amber warning banner** is visible at the top of the "Inferred Factory" panel
- Banner title: "⚠️ Using Demo Factory"
- Banner message explains parsing failed
- "Issues encountered:" section may list errors (depending on what the LLM extracted)
- **Blue notice** appears at the top of "Scenarios & Metrics" panel
- Notice says: "The scenarios and metrics below are based on the demo factory, not your original input"

### Verification

In browser DevTools → Network, check simulate response:
```json
{
  "meta": {
    "used_default_factory": true,
    "onboarding_errors": [
      "<some error message about parsing failure>"
    ],
    "inferred_assumptions": []
  }
}
```

---

## Test Case 3: Fallback with LLM Timeout (Banner + Error Details)

**Objective:** Verify that LLM errors are captured and displayed in the banner.

### Steps

1. **Note:** This test requires mocking an LLM timeout, which isn't easy in manual UI testing.

   **Alternative approach:** Use the unit tests instead:
   ```bash
   python -m pytest backend/tests/test_server_simulate.py::TestSimulateEndpointMetaPropagation -v
   ```

   These tests verify that:
   - `used_default_factory` is correctly propagated
   - `onboarding_errors` list is correctly propagated
   - Banners will display them when present

### What the Code Tests

The `TestSimulateEndpointMetaPropagation` class includes three tests:

1. `test_simulate_endpoint_propagates_used_default_factory_flag`
   - Mocks LLM timeout
   - Verifies `used_default_factory=True` reaches frontend

2. `test_simulate_endpoint_propagates_onboarding_errors`
   - Mocks two onboarding errors
   - Verifies both are in response and reach frontend

3. `test_simulate_endpoint_meta_on_success`
   - Mocks successful onboarding
   - Verifies `used_default_factory=False` and empty errors

---

## Visual Inspection Checklist

After implementing PR5, verify these visual elements:

### Fallback Banner Styling
- [ ] Amber/yellow background color (should be `#fff3cd`)
- [ ] Darker amber border (should be `#ffc107`, 2px solid)
- [ ] Dark text (should be `#856404`)
- [ ] Warning emoji visible: ⚠️
- [ ] "Using Demo Factory" header is bold
- [ ] Message text is readable and explains the situation
- [ ] If errors present, they appear in a box with "Issues encountered:" header
- [ ] Errors are bulleted or listed clearly

### Fallback Notice Styling
- [ ] Light blue background (should be `#e7f3ff`)
- [ ] Subtle blue border (should be `#b3d9ff`, 1px solid)
- [ ] Dark blue text (should be `#004085`)
- [ ] "Note:" prefix is bold
- [ ] Message is concise and informative
- [ ] Positioned at top of scenarios panel, before metrics table

### Positioning & Visibility
- [ ] Banner is visible without scrolling in typical viewport
- [ ] Banner doesn't overlap factory data below it
- [ ] Notice doesn't overlap metrics table
- [ ] Both banners only appear when `used_default_factory=true`
- [ ] When `used_default_factory=false`, no banners appear

---

## Browser DevTools Debugging

### Inspect the Response Data

1. Open DevTools (F12)
2. Go to Network tab
3. Click "Simulate" in the app
4. Find the "simulate" request
5. Click it, then go to Response tab
6. Look for `meta.used_default_factory` and `meta.onboarding_errors`

### Inspect the React Props

1. Open DevTools, go to Console
2. The `result` object contains:
   ```javascript
   result.meta.used_default_factory // Should be true/false
   result.meta.onboarding_errors    // Should be empty [] or have error strings
   ```

### Inspect CSS Classes

1. Right-click on the banner → "Inspect"
2. Verify the element has class `fallback-banner` or `fallback-notice`
3. In the Styles pane, verify the CSS matches PR5:
   - `.fallback-banner` has `background-color: #fff3cd`
   - `.fallback-notice` has `background-color: #e7f3ff`

---

## Responsive Design Testing

Test on different viewport sizes to ensure banners display properly:

1. **Desktop (1920x1080)**
   - [ ] Banner spans full width of panel
   - [ ] Text wraps nicely
   - [ ] No overflow issues

2. **Tablet (768x1024)**
   - [ ] Banner still visible and readable
   - [ ] Font sizes remain appropriate
   - [ ] Errors list still formatted well

3. **Mobile (375x667)**
   - [ ] Banner adapts to narrow width
   - [ ] Text remains readable
   - [ ] No horizontal scrolling needed

---

## Accessibility Check (Optional)

1. **Color Contrast:** Use a contrast checker tool
   - Amber text (#856404) on amber background (#fff3cd): Should be WCAG AA compliant
   - Blue text (#004085) on blue background (#e7f3ff): Should be WCAG AA compliant

2. **Semantic HTML:**
   - Use DevTools Inspector to verify banners use proper `<div>` elements
   - Text elements should be readable by screen readers

3. **Keyboard Navigation:**
   - Tab through the interface
   - Ensure focus indicators are visible
   - Verify all interactive elements are reachable

---

## Test Results Summary

After completing all tests, you should be able to confirm:

✅ **Test Case 1:** Successful parsing shows no banners
✅ **Test Case 2:** Failed parsing shows yellow banner with clear messaging
✅ **Test Case 3:** Unit tests verify error propagation works correctly
✅ **Visual Checks:** All styling matches design spec
✅ **Responsive Design:** Banners work on all viewport sizes
✅ **Accessibility:** Text is readable and elements are accessible

---

## Common Issues & Troubleshooting

### Issue: Banner doesn't appear when it should

**Solution:**
1. Check browser console (F12 → Console) for any JavaScript errors
2. Verify backend is returning `meta.used_default_factory = true`
3. Verify TypeScript compiled successfully: `npm run build`
4. Clear browser cache (Ctrl+Shift+Delete) and refresh

### Issue: Banner appears but styling looks wrong

**Solution:**
1. Check that CSS file was updated correctly: `frontend/src/App.css`
2. Verify class names match: `fallback-banner` or `fallback-notice`
3. Check that color values are correct (not typos)
4. Rebuild frontend: `npm run build`

### Issue: Error messages aren't showing in the banner

**Solution:**
1. Check that `onboarding_errors` is being populated by backend
2. Verify the response JSON includes `meta.onboarding_errors` array
3. Check browser console for JavaScript errors
4. Verify App.tsx mapping logic: `meta.onboarding_errors.map(...)`

---

## Files to Review

- **Component Logic:** `frontend/src/App.tsx` lines 101-165 (fallback banner rendering)
- **Styling:** `frontend/src/App.css` lines 116-173 (fallback banner & notice styles)
- **Type Safety:** `frontend/src/api.ts` (OnboardingMeta interface should be unchanged)
- **Tests:** `backend/tests/test_server_simulate.py::TestSimulateEndpointMetaPropagation`

---

## Next Steps

After manual testing, if all checks pass:

1. Take a screenshot of the fallback banner for documentation
2. Note any UI improvements or tweaks needed for future PRs
3. Consider adding E2E tests (Cypress/Playwright) for automated banner testing
4. Track user feedback on banner clarity and usefulness
