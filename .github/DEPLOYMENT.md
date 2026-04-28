# Deployment Guide

## GitHub Actions NPM Publishing Workflow

This repository uses GitHub Actions to automatically publish the `main-nodejs` branch to npm under the `@weaveaijs` organization.

### Workflow Overview

The deployment workflow (`.github/workflows/publish.yml`) performs the following steps:

1. **Build & Test** (Runs on Node 18.x and 20.x)
   - Installs dependencies
   - Compiles TypeScript
   - Runs test suite
   - Verifies build artifacts

2. **Publish to npm**
   - Checks if version is already published (prevents duplicate publishes)
   - Publishes to npm as `@weaveaijs/mcp-observatory`
   - Creates a GitHub release
   - Posts deployment notification

### Setup Requirements

#### 1. Configure NPM Token Secret

To enable automatic publishing to npm, you need to configure the `NPM_TOKEN` secret in GitHub:

1. Generate an npm access token:
   - Visit https://www.npmjs.com/settings/tokens
   - Click "Generate New Token" (Granular Access Token recommended)
   - Grant permissions:
     - `read:packages`
     - `write:packages`
     - `publish:packages`
   - Scope: Limit to the `@weaveaijs` organization
   - Expiration: Set appropriately (e.g., 90 days)

2. Add to GitHub repository secrets:
   - Go to: Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Name: `NPM_TOKEN`
   - Value: Paste the token from step 1
   - Click "Add secret"

#### 2. Verify npm Organization Access

Ensure your npm user account is:
- A member of the `@weaveaijs` organization
- Has permissions to publish packages

You can verify this with:
```bash
npm org ls @weaveaijs
```

### Deployment Triggers

The workflow automatically publishes when:

1. **Push to main-nodejs branch** with changes to:
   - `package.json` (version bump)
   - Source files in `src/`
   - The workflow file itself (`.github/workflows/publish.yml`)

2. **Manual trigger** via GitHub Actions UI:
   - Visit Actions → "Publish to npm (@weaveaijs)"
   - Click "Run workflow"
   - Select `main-nodejs` branch

### Version Management

To publish a new version:

1. Update the version in `package.json`:
   ```json
   {
     "version": "0.4.0"
   }
   ```

2. Commit the change:
   ```bash
   git commit -m "chore: bump version to 0.4.0"
   ```

3. Push to `main-nodejs`:
   ```bash
   git push origin main-nodejs
   ```

4. The workflow will automatically:
   - Build and test the package
   - Check if version is already published
   - Publish to npm
   - Create a GitHub release
   - Send notifications

### Preventing Duplicate Publishes

The workflow includes version checking to prevent publishing the same version twice:

```yaml
- name: Check if version already published
  id: check-version
  continue-on-error: true
  run: |
    npm view @weaveaijs/mcp-observatory@${{ steps.package-version.outputs.version }} > /dev/null
```

If the version already exists, publishing is skipped.

### Monitoring Deployments

#### View Workflow Runs

1. Go to: Repository → Actions
2. Select "Publish to npm (@weaveaijs)" workflow
3. View run history with status and logs

#### View Published Package

- npm.js: https://www.npmjs.com/package/@weaveaijs/mcp-observatory
- Package registry API: https://registry.npmjs.org/@weaveaijs/mcp-observatory

#### Installation

After publishing, users can install with:

```bash
npm install @weaveaijs/mcp-observatory
```

Or with yarn:

```bash
yarn add @weaveaijs/mcp-observatory
```

### Build Matrix

The workflow tests on multiple Node versions:
- **Node 18.x** - LTS (even)
- **Node 20.x** - Latest LTS

This ensures compatibility across common Node versions.

### Troubleshooting

#### NPM_TOKEN not set
- **Error**: `401 Unauthorized`
- **Solution**: Check that `NPM_TOKEN` secret is configured in repository settings

#### Permission Denied
- **Error**: `403 You do not have permission to publish to @weaveaijs`
- **Solution**: Verify npm organization membership and token permissions

#### Version Already Published
- **Error**: `You cannot publish over the previously published version`
- **Solution**: Bump the version in `package.json` before publishing

#### Build Failures
- **Error**: Tests fail or TypeScript compilation errors
- **Solution**: Check GitHub Actions logs for specific errors, fix in code, and push again

### Manual Publishing (if needed)

If automatic publishing fails, you can publish manually:

```bash
# Build the project
npm run build

# Authenticate with npm
npm login --scope=@weaveaijs

# Publish
npm publish
```

### Security Considerations

- **Token Scoping**: Use granular access tokens with minimal permissions
- **Token Rotation**: Regularly rotate tokens (every 90 days recommended)
- **Audit Logs**: Check npm audit logs for any suspicious activity
- **Branch Protection**: Only merge to `main-nodejs` after code review
- **Artifact Verification**: Verify published package checksums match build artifacts

### CI/CD Best Practices

1. ✅ All tests must pass before publishing
2. ✅ Version bump in `package.json` only (avoid manual tagging)
3. ✅ Create releases for each npm publication
4. ✅ Monitor npm package stats and downloads
5. ✅ Document breaking changes in release notes
6. ✅ Use semantic versioning (MAJOR.MINOR.PATCH)

### Rollback Procedure

If a bad version is published, use npm unpublish:

```bash
npm unpublish @weaveaijs/mcp-observatory@<version>
```

Or deprecate it:

```bash
npm deprecate @weaveaijs/mcp-observatory@<version> "Version X deprecated, use X.X.X instead"
```

### Related Resources

- [npm Publishing Guide](https://docs.npmjs.com/creating-and-publishing-unscoped-public-packages)
- [GitHub Actions: Publishing Node.js packages](https://docs.github.com/en/actions/publishing-packages/publishing-nodejs-packages)
- [npm Organization Docs](https://docs.npmjs.com/creating-an-organization)
- [Semantic Versioning](https://semver.org/)
