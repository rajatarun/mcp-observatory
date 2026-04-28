# NPM Publishing Setup Guide

## Quick Start

Your `main-nodejs` branch is now configured to automatically publish to npm as `@weaveaijs/mcp-observatory`. 

Follow these steps to enable automatic publishing:

### Step 1: Create NPM Access Token

1. Visit [npm tokens page](https://www.npmjs.com/settings/tokens)
2. Click **"Generate New Token"** → Select **"Granular Access Token"**
3. Configure token:
   - **Token name**: `github-actions-weaveaijs-mcp`
   - **Expiration**: 90 days (or your preferred interval)
   - **Permissions**:
     - ✅ `read:packages`
     - ✅ `write:packages`
     - ✅ `publish:packages`
   - **Organization scope**: Limit to `@weaveaijs` (recommended)
4. Copy the generated token (you won't see it again)

### Step 2: Add NPM_TOKEN to GitHub Secrets

1. Go to your repository: **Settings** → **Secrets and variables** → **Actions**
2. Click **"New repository secret"**
3. Configure:
   - **Name**: `NPM_TOKEN`
   - **Value**: Paste the token from Step 1
4. Click **"Add secret"**

### Step 3: Verify npm Organization Access

Ensure your account has publishing rights:

```bash
npm org ls @weaveaijs
```

You should see your username in the members list with `developer` or higher role.

### Step 4: Test the Workflow

The workflow will automatically trigger when you:

#### Option A: Update Version and Push

```bash
# On main-nodejs branch
npm version minor  # or patch/major
git push origin main-nodejs
```

The workflow will:
- ✅ Build on Node 18.x and 20.x
- ✅ Run all tests
- ✅ Publish to npm if version is new
- ✅ Create a GitHub release

#### Option B: Manual Trigger

1. Go to **Actions** → **"Publish to npm (@weaveaijs)"**
2. Click **"Run workflow"**
3. Select `main-nodejs` branch
4. Click **"Run workflow"**

## Workflow Files

### `.github/workflows/publish.yml`

Triggered on:
- Push to `main-nodejs` with changes to:
  - `package.json`
  - `src/**` files
  - Workflow file itself
- Manual trigger via Actions UI

Jobs:
1. **build-and-test**: Validates on Node 18.x & 20.x
2. **publish**: Publishes to npm and creates release

### `.github/workflows/test.yml`

Triggered on:
- Every push to `main-nodejs`
- Every pull request targeting `main-nodejs`

Validates:
- Build succeeds
- Tests pass
- All build artifacts exist
- Code quality passes (linting)

## Publishing Workflow

```
Developer commits → Push to main-nodejs
                          ↓
                    GitHub Actions
                          ↓
                 Build & Test (Node 18, 20)
                          ↓
                   Tests Pass? 
                    ↙        ↘
                  Yes        No → ❌ Publish fails
                   ↓
            Check npm registry
                   ↓
         Version already published?
            ↙                    ↘
           Yes                    No
           ↓                      ↓
        Skip              Publish to npm
                          Create Release
                          ✅ Success
```

## Version Management

### Before Publishing

1. **Bump version** in `package.json`:
   ```json
   {
     "version": "0.4.0"
   }
   ```

2. **Use semantic versioning**:
   - `MAJOR.MINOR.PATCH`
   - `0.3.0` → `0.3.1` (patch - bug fixes)
   - `0.3.0` → `0.4.0` (minor - features)
   - `0.3.0` → `1.0.0` (major - breaking changes)

3. **Commit change**:
   ```bash
   git add package.json
   git commit -m "chore: bump version to 0.4.0"
   git push origin main-nodejs
   ```

### After Publishing

GitHub Actions will:
1. Build and test the package
2. Check if `@weaveaijs/mcp-observatory@0.4.0` already exists
3. Publish to npm registry
4. Create a GitHub release with tags
5. Post deployment confirmation

### View Published Package

- **npm.js**: https://www.npmjs.com/package/@weaveaijs/mcp-observatory
- **GitHub Releases**: `/releases` page of your repo

## Installation for Users

After publishing, users can install:

```bash
npm install @weaveaijs/mcp-observatory
```

Or add to `package.json`:

```json
{
  "dependencies": {
    "@weaveaijs/mcp-observatory": "^0.4.0"
  }
}
```

## Configuration Files

### `package.json`

Already configured with:
```json
{
  "name": "@weaveaijs/mcp-observatory",
  "publishConfig": {
    "access": "public",
    "registry": "https://registry.npmjs.org"
  }
}
```

### `.npmrc`

Registry configuration:
```
@weaveaijs:registry=https://registry.npmjs.org/
```

## Troubleshooting

### 401 Unauthorized

**Issue**: Workflow fails with "401 Unauthorized"

**Solutions**:
1. Check `NPM_TOKEN` is set in GitHub Secrets
2. Verify token hasn't expired (regenerate if needed)
3. Confirm token has `publish:packages` permission

### 403 Permission Denied

**Issue**: "You do not have permission to publish to @weaveaijs"

**Solutions**:
1. Verify npm user is member of `@weaveaijs` org
2. Check user role (needs `developer` or higher)
3. Re-generate token if inherited permissions changed

### Version Already Published

**Issue**: "You cannot publish over the previously published version"

**Solution**:
- The workflow detects this and skips publishing
- Bump version in `package.json` and push again

### Build Failed

**Issue**: Tests fail or TypeScript errors

**Solutions**:
1. Check GitHub Actions logs for specific error
2. Run `npm run build && npm test` locally
3. Fix issues and push again

### Tests Fail

**Common reasons**:
- Node version mismatch (test on Node 18+)
- Missing dependencies (`npm ci`)
- Outdated TypeScript definitions
- PostgreSQL test requirements

**Debug**:
```bash
npm ci
npm run build
npm test
```

## Manual Publishing (Emergency)

If automatic workflow fails completely:

```bash
# Ensure authenticated
npm login --scope=@weaveaijs

# Build locally
npm run build

# Publish manually
npm publish

# Or with detailed output
npm publish --verbose
```

## Monitoring

### GitHub Actions

View workflow runs:
1. Repository → **Actions** tab
2. Select **"Publish to npm (@weaveaijs)"**
3. View run history and logs

### npm Registry

Monitor package stats:
- https://www.npmjs.com/package/@weaveaijs/mcp-observatory/analytics
- Downloads per week
- Dependent packages
- Network impact

## Security Best Practices

✅ **Do**:
- Rotate tokens every 90 days
- Use granular access tokens (not classic)
- Limit token scope to `@weaveaijs` organization
- Audit npm organization members regularly
- Review GitHub Actions logs for suspicious activity
- Require code review before merging to `main-nodejs`
- Tag releases with version numbers

❌ **Don't**:
- Commit `.npmrc` files with tokens
- Share tokens via email or Slack
- Use personal npm access tokens
- Publish directly without CI/CD
- Skip tests before publishing
- Remove published versions (use deprecation instead)

## What's Automated

✅ **Automated by GitHub Actions**:
- Build TypeScript → JavaScript
- Run all tests
- Check version uniqueness
- Publish to npm
- Create GitHub releases
- Post notifications

❌ **Manual Steps**:
- Update version in `package.json`
- Create commit message
- Push to `main-nodejs`
- Review GitHub Actions status
- Monitor npm downloads

## Release Checklist

Before each release:

- [ ] Update `package.json` version
- [ ] Review git log for changes
- [ ] Run tests locally: `npm test`
- [ ] Build locally: `npm run build`
- [ ] Commit: `git commit -m "chore: release vX.X.X"`
- [ ] Push to `main-nodejs`: `git push origin main-nodejs`
- [ ] Monitor GitHub Actions
- [ ] Verify on npm registry
- [ ] Check GitHub release was created

## Next Steps

1. ✅ Create NPM_TOKEN and add to GitHub Secrets
2. ✅ Test with `npm version patch`
3. ✅ Monitor first automatic publish
4. 📚 Read `.github/DEPLOYMENT.md` for advanced topics
5. 📦 Watch npm downloads grow!

## Questions?

- **GitHub Actions Docs**: https://docs.github.com/en/actions
- **npm Publishing**: https://docs.npmjs.com/creating-and-publishing-unscoped-public-packages
- **Repository Issues**: Create an issue for help

---

**Ready to publish?** Bump the version and push! GitHub Actions will handle the rest. 🚀
