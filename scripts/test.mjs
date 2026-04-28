import { globSync } from 'glob';
import { execSync } from 'child_process';

// Find all test files
const testFiles = globSync('dist/tests/**/*.test.js');

if (testFiles.length === 0) {
  console.error('No test files found');
  process.exit(1);
}

console.log(`Found ${testFiles.length} test files:`);
testFiles.forEach(file => console.log(`  - ${file}`));

// Run tests
try {
  const command = `node --test ${testFiles.join(' ')}`;
  execSync(command, { stdio: 'inherit' });
} catch (error) {
  process.exit(1);
}
