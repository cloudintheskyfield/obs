# Playwright E2E Testing Framework

A comprehensive Playwright testing framework featuring Page Object Model architecture, accessibility testing, API validation, multi-environment support, and advanced test automation capabilities. Perfect for creating robust, maintainable end-to-end test suites with built-in best practices.

## Quick Start

Generate a complete test suite:

```
"Create E2E tests for the login feature with accessibility checks"
```

Create API tests with validation:

```
"Generate API tests for the user service with schema validation"
```

Add accessibility testing:

```
"Add accessibility tests for the homepage using axe-core"
```

Build tagged test suites:

```
"Create a smoke test suite with @smoke tag for critical user flows"
```

Multi-environment testing:

```
"Run tests against staging environment"
```

## Quick Reference

| Deliverable | What You Get | Time |
|-------------|--------------|------|
| E2E Test Suite | Complete tests with POM, fixtures, selectors | 15-20 min |
| API Tests | Endpoint tests with Zod schema validation | 10-15 min |
| Accessibility Suite | A11y tests with axe-core, WCAG compliance | 10-12 min |
| Smoke Tests | Critical path tests with @smoke tags | 8-10 min |
| Visual Regression | Screenshot comparison tests | 5-8 min |

## How It Works

```
Your Request
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ 1. ANALYZE                                          │
│    • Parse feature requirements                     │
│    • Identify test patterns needed                  │
│    • Determine page objects and fixtures            │
├─────────────────────────────────────────────────────┤
│ 2. GENERATE                                         │
│    • Create spec files with test.describe()         │
│    • Build page objects with locators               │
│    • Add accessibility checks if needed             │
│    • Include API validation with Zod schemas        │
├─────────────────────────────────────────────────────┤
│ 3. STRUCTURE                                        │
│    • Apply POM architecture                         │
│    • Use fixtures for dependency injection          │
│    • Add test.step() for clarity                    │
│    • Tag tests appropriately (@smoke, @a11y)        │
└─────────────────────────────────────────────────────┘
    │
    ▼
Production-Ready Test Suite
```

## Core Capabilities

### 1. Page Object Model Architecture

**Structure:**
- Base page with reusable methods
- Feature-specific page objects
- Selector management separate from logic
- Custom fixtures for page injection

**Example:**
```typescript
// pages/login/login.page.ts
export class LoginPage extends BasePage {
    async login(username: string, password: string) {
        await this.page.getByPlaceholder("Enter username").fill(username);
        await this.page.getByPlaceholder("Enter password").fill(password);
        await this.page.getByRole('button', { name: "login" }).click();
    }
}
```

### 2. Accessibility Testing

**Built-in A11y Features:**
- Axe-core integration
- WCAG 2.0 AA/AAA compliance checks
- Automated violation reporting
- Attach scan results to test reports

**BasePage A11y Method:**
```typescript
await homePage.checkA11y();
```

### 3. API Testing with Schema Validation

**Features:**
- API client with base methods
- Zod schema validation
- Request/response typing
- Authentication management
- Structured error handling

**Example:**
```typescript
const response = await apiClient.createService(serviceData);
const validatedData = ApiServiceResponseSchema.parse(response.data);
```

### 4. Multi-Environment Support

**Configurations:**
- Local, dev, staging, production
- Environment-specific baseUrls
- Dynamic configuration switching
- Environment variable management

**Usage:**
```bash
TEST_ENV=stage npm run test
TEST_ENV=prod npm run test
```

### 5. Tag-Based Test Execution

**Available Tags:**
- `@smoke` - Critical path tests
- `@a11y` - Accessibility tests
- Custom tags for features

**Example:**
```typescript
test.describe('Home Layout', { tag: ['@smoke'] }, () => {
    // Critical tests here
});
```

**Run Tagged Tests:**
```bash
npm run test:smoke  # Only @smoke tests
npx playwright test --grep @a11y  # Only a11y tests
```

### 6. Visual Regression Testing

**Features:**
- Screenshot comparison
- Configurable diff thresholds
- Component-level snapshots
- Full-page screenshots

**Example:**
```typescript
await homePage.takeQuerySnapshot("body", "home-page");
```

## Test Structure Best Practices

### Standard E2E Test Format

```typescript
import { test, expect } from '../../fixtures/base';
import config from '../../../playwright.config';

const envPage = config.baseUrl;

test.describe('Feature Name', { tag: ['@smoke'] }, () => {
    test.beforeEach(async ({ featurePage }) => {
        await featurePage.goto(envPage);
    });

    test('Feature - Specific behavior', async ({ featurePage, page }) => {
        await test.step('Clear description of step', async () => {
            // Test logic here
            await featurePage.performAction();
            await expect(page.getByRole('button')).toBeVisible();
        });
    });
});
```

### API Test Format

```typescript
import { test, expect } from '../../fixtures/base';

test.describe('API - Service Tests', { tag: ['@api'] }, () => {
    test('API - Create and retrieve service', async ({ apiClient }) => {
        const service = await apiClient.createService(testData);
        expect(service.id).toBeDefined();
        
        const retrieved = await apiClient.getService(service.id);
        expect(retrieved.data).toEqual(service.data);
    });
});
```

### Accessibility Test Format

```typescript
test('Accessibility - Homepage compliance', async ({ homePage }, testInfo) => {
    const violations = await homePage.checkA11y();
    
    await testInfo.attach('accessibility-scan-results', {
        body: JSON.stringify(violations, null, 2),
        contentType: 'application/json'
    });
    
    expect(violations).toHaveLength(0);
});
```

## Commands

### Test Execution

| Command | Purpose |
|---------|---------|
| `npm run test` | Run all tests |
| `npm run test:smoke` | Run smoke tests only |
| `npm run test:failed` | Rerun failed tests |
| `npm run test:ui` | Launch Playwright UI mode |

### Environment-Specific

| Command | Purpose |
|---------|---------|
| `TEST_ENV=dev npm run test` | Run against dev environment |
| `TEST_ENV=stage npm run test` | Run against staging |
| `TEST_ENV=prod npm run test` | Run against production |

### CI/CD Simulation

```bash
npx playwright test -g "@smoke" --repeat-each=100 --workers=10 -x
```

### Natural Language Commands

| Command | What It Does |
|---------|--------------|
| "Create E2E test for {feature}" | Complete test with POM and fixtures |
| "Add accessibility test for {page}" | A11y test with axe-core integration |
| "Generate API tests for {endpoint}" | API tests with schema validation |
| "Create smoke test suite for {flow}" | Tagged smoke tests for critical path |
| "Add visual regression for {component}" | Screenshot comparison test |

## Framework Features

### BasePage Utilities

**Built-in Methods:**
- `goto(url)` - Navigate with wait for load
- `checkA11y()` - Run accessibility scan
- `takeQuerySnapshot(locator, name)` - Visual regression
- `takeFullPageScreenshot()` - Full page capture
- `hoverAndClick(locator)` - Hover then click
- `getTrimmedText(locator)` - Get cleaned text content
- `waitForText(locator, text)` - Wait for specific text
- `getAllLinksFromPage(page)` - Extract all valid links

### Custom Fixtures

**Available Fixtures:**
- `basePage` - Base page instance
- `homePage` - Home page instance
- `apiClient` - API client with auth
- Custom page fixtures as needed

**Usage:**
```typescript
test('My test', async ({ homePage, apiClient }) => {
    // Fixtures automatically injected
});
```

### State Management

**Auth State Persistence:**
```typescript
await page.context().storageState({ path: STORAGE_STATE });
```

**Config Setting:**
```typescript
use: {
    storageState: "./e2e/fixtures/auth.json"
}
```

### Device and Browser Matrix

**Configured Devices:**
- Desktop Chrome
- Desktop Firefox
- Desktop Safari
- Mobile Chrome (Pixel 5)
- Mobile Safari (iPhone 12)

**Configuration:**
```typescript
projects: [...deviceMatrix]
```

## Anti-Patterns

| ❌ Don't Do | ✅ Do Instead |
|------------|--------------|
| Use `page.waitForTimeout()` | Use auto-retrying assertions |
| Hard-code URLs in tests | Use `config.baseUrl` |
| Skip page objects | Create reusable page classes |
| Ignore accessibility | Use `checkA11y()` regularly |
| Use CSS selectors everywhere | Prefer `getByRole`, `getByLabel` |
| Skip test.step() | Wrap actions in clear steps |
| Forget tags | Tag tests for organization |
| Skip schema validation | Validate API responses with Zod |

## Verification Checklist

**Test Structure:**
- ✓ Uses fixtures for page objects
- ✓ Follows POM architecture
- ✓ Groups tests in `test.describe()`
- ✓ Uses `beforeEach` for setup
- ✓ Wrapped in `test.step()` for clarity

**Locators:**
- ✓ User-facing locators (`getByRole`, `getByLabel`)
- ✓ Avoid strict mode violations
- ✓ Specific and accessible selectors
- ✓ Separated in selector files when complex

**Assertions:**
- ✓ Auto-retrying web-first assertions
- ✓ Meaningful assertion messages
- ✓ Proper `await` usage
- ✓ Soft assertions where appropriate

**Configuration:**
- ✓ Appropriate tags applied
- ✓ Environment configured correctly
- ✓ Timeouts reasonable
- ✓ Reporters configured

## Test Types

| Type | Purpose | Example Use Case |
|------|---------|-----------------|
| Functional | Business logic verification | Login with valid credentials |
| UI/Visual | Appearance, layout, responsive | Button matches design specs |
| Integration | Component interaction | API data displays in UI |
| Smoke | Critical paths (@smoke) | Core features work after deploy |
| Accessibility | WCAG compliance (@a11y) | No a11y violations on page |
| Regression | Existing functionality | Previous features still work |
| API | Backend validation | Endpoints return correct data |

## Reporting

### Built-in Reporters

**Configured Reporters:**
- Blob reporter (for merge)
- HTML reporter (interactive)
- List reporter (console)
- GitHub reporter (annotations)
- Custom state reporter

**Outputs:**
```
playwright-report/      # HTML report
e2e/reports/
  ├── test-results/     # Test artifacts
  ├── snapshots/        # Screenshot baselines
  └── screenshots/      # Failed test screenshots
```

### Trace Viewing

```bash
npx playwright show-trace trace.zip
```

**Trace Includes:**
- Screenshots
- Network requests
- Console logs
- DOM snapshots
- Action timeline

## Configuration Options

### Lighthouse Audits

```typescript
lighthouseAudit: false  // Toggle performance audits
```

### Component Snapshots

```typescript
componentSnapshots: true  // Enable visual regression
```

### Screenshot Settings

```typescript
const screenshotOptions = {
    maxDiffPixelRatio: 0.15
};
```

## Advanced Patterns

### Geolocation Testing

```typescript
const geolocationUsers = {
    eastCoast: {
        geolocation: { longitude: -74.006, latitude: 40.7128 },
        timezoneId: "America/New_York"
    }
};
```

### Console Error Detection

```typescript
test('Home - should not have console errors', async ({ page }) => {
    const errors: Error[] = [];
    page.on('pageerror', (error) => {
        errors.push(error);
    });
    // Perform actions
    expect(errors).toHaveLength(0);
});
```

### Link Validation

```typescript
const linkUrls = await homePage.getAllLinksFromPage(page);
for (const url of linkUrls) {
    const response = await page.request.get(url);
    expect.soft(response.ok()).toBeTruthy();
}
```

## Best Practices

### Test Writing

**DO:**
- Use Page Object Model
- Apply clear test.step() descriptions
- Tag tests appropriately
- Use fixtures for setup
- Write accessible locators
- Validate with auto-retrying assertions
- Keep tests independent

**DON'T:**
- Mix test logic with page logic
- Use hard waits unnecessarily
- Hard-code environment URLs
- Skip accessibility checks
- Ignore failed tests in CI
- Create brittle selectors

### API Testing

**DO:**
- Validate responses with Zod schemas
- Use type-safe request/response
- Authenticate before protected requests
- Handle errors explicitly
- Test both success and error paths

**DON'T:**
- Skip schema validation
- Ignore response status codes
- Test without authentication
- Forget to test edge cases

### Maintenance

**DO:**
- Keep page objects DRY
- Update selectors in one place
- Maintain fixture structure
- Review and update tags
- Keep dependencies current
- Clean up test data

**DON'T:**
- Duplicate page methods
- Scatter selectors throughout tests
- Leave obsolete fixtures
- Ignore deprecation warnings

## CI/CD Integration

### Example GitHub Actions

```yaml
- name: Install dependencies
  run: npm install

- name: Install Playwright browsers
  run: npx playwright install --with-deps

- name: Run smoke tests
  run: npm run test:smoke
  env:
    TEST_ENV: stage

- name: Upload report
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: playwright-report
    path: playwright-report/
```

### Retry Strategy

```typescript
retries: process.env.CI ? 2 : 0
workers: process.env.CI ? 1 : undefined
```

## Examples

### Complete Login Test

```typescript
import { test, expect } from '../../fixtures/base';
import config from '../../../playwright.config';

test.describe('Authentication', { tag: ['@smoke'] }, () => {
    test('Login - Valid user can authenticate', async ({ page, loginPage }) => {
        await test.step('Navigate to login page', async () => {
            await loginPage.goto(`${config.baseUrl}/login`);
        });

        await test.step('Enter credentials and submit', async () => {
            await page.getByPlaceholder("Enter username").fill("testuser");
            await page.getByPlaceholder("Enter password").fill("password123");
            await page.getByRole('button', { name: "login" }).click();
        });

        await test.step('Verify successful login', async () => {
            await expect(page.getByRole('button', { name: "Profile" })).toBeVisible();
            await expect(page).toHaveURL(/dashboard/);
        });
    });
});
```

### Complete API Test with Validation

```typescript
import { test, expect } from '../../fixtures/api.fixture';
import { submitForm } from '../../fixtures/dataFactory';

test.describe('API - User Service', { tag: ['@api'] }, () => {
    test('API - Create user and validate response', async ({ apiClient }) => {
        await test.step('Authenticate API client', async () => {
            await apiClient.authenticate({
                username: process.env.USERNAME!,
                password: process.env.PASSWORD!
            });
        });

        const userData = submitForm();

        await test.step('Create new user', async () => {
            const response = await apiClient.createNewUser(userData);
            
            expect(response.status).toBe(201);
            expect(response.data.email).toBe(userData.email);
            expect(response.data.id).toBeDefined();
        });
    });
});
```

### Accessibility Test with Reporting

```typescript
import { test, expect } from '../../fixtures/base';
import config from '../../../playwright.config';

test.describe('Accessibility', { tag: ['@a11y'] }, () => {
    test('A11y - Homepage WCAG compliance', async ({ homePage }, testInfo) => {
        await test.step('Navigate to homepage', async () => {
            await homePage.goto(config.baseUrl);
        });

        await test.step('Run accessibility scan', async () => {
            const violations = await homePage.checkA11y();
            
            await testInfo.attach('accessibility-scan-results', {
                body: JSON.stringify(violations, null, 2),
                contentType: 'application/json'
            });

            expect(violations, 'No accessibility violations found').toHaveLength(0);
        });
    });
});
```

### Visual Regression Test

```typescript
test('Visual - Homepage layout matches baseline', async ({ homePage }) => {
    await test.step('Navigate and capture snapshot', async () => {
        await homePage.goto(config.baseUrl);
        await homePage.takeQuerySnapshot("body", "homepage-full");
    });

    await test.step('Capture component snapshot', async () => {
        await homePage.takeQuerySnapshot(".navigation", "nav-component");
    });
});
```

## Troubleshooting

### Common Issues

**Issue: Tests fail in CI but pass locally**
- Solution: Check CI environment variables, ensure consistent browser versions, verify network conditions

**Issue: Flaky tests due to timing**
- Solution: Replace hard waits with auto-retrying assertions, use `waitForLoadState`, check for loading indicators

**Issue: Cannot find locator**
- Solution: Use Playwright Inspector (`PWDEBUG=1`), prefer `getByRole` over CSS selectors, check for visibility issues

**Issue: Schema validation fails**
- Solution: Verify API response structure, update Zod schemas, check for nullable fields

**Issue: Screenshot comparison fails**
- Solution: Update baseline with `--update-snapshots`, adjust `maxDiffPixelRatio`, ensure consistent viewport

## References

### Documentation Links

- [Playwright Official Docs](https://playwright.dev)
- [Axe-core Accessibility Rules](https://github.com/dequelabs/axe-core)
- [Zod Schema Validation](https://zod.dev)
- [Page Object Model Pattern](https://playwright.dev/docs/pom)

### Framework Structure

```
e2e/
├── fixtures/          # Test fixtures and dependency injection
├── helpers/           # Utility functions and API clients
├── pages/             # Page Object Model classes
├── reports/           # Test outputs and reports
├── scripts/           # Agent automation scripts
└── specs/             # Test specification files
    ├── accessibility/ # A11y test suites
    ├── api/           # API test suites
    ├── auth/          # Authentication tests
    └── home/          # Homepage test suites
```

---

**"Quality is never an accident; it is always the result of intelligent effort."** - John Ruskin

**"The best error message is the one that never shows up."** - Thomas Fuchs
