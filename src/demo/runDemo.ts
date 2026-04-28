import { runServerDemo } from './server.js';
import { runClientDemo } from './client.js';

async function main(): Promise<void> {
  try {
    await runServerDemo();
    console.log('\n' + '='.repeat(50) + '\n');
    await runClientDemo();
  } catch (error) {
    console.error('Demo error:', error);
    process.exit(1);
  }
}

main();
