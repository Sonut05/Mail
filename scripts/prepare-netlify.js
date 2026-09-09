/**
 * Cross-platform build preparation script for Netlify deployment.
 * Bundles backend app modules and dependencies into netlify/functions
 * without relying on shell-specific commands.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

const backendDir = path.join(rootDir, 'backend');
const backendAppDir = path.join(backendDir, 'app');
const netlifyFunctionsDir = path.join(rootDir, 'netlify', 'functions');
const netlifyAppDir = path.join(netlifyFunctionsDir, 'app');
const backendReqsFile = path.join(backendDir, 'requirements.txt');
const netlifyReqsFile = path.join(netlifyFunctionsDir, 'requirements.txt');
const rootReqsFile = path.join(rootDir, 'requirements.txt');

console.log('🚀 [MailMind Netlify Packager] Starting Netlify bundle preparation...');

// 1. Ensure netlify/functions directory exists
if (!fs.existsSync(netlifyFunctionsDir)) {
  fs.mkdirSync(netlifyFunctionsDir, { recursive: true });
  console.log('  ✔ Created netlify/functions directory');
}

// 2. Synchronize requirements.txt from authoritative backend/requirements.txt
if (fs.existsSync(backendReqsFile)) {
  const reqsContent = fs.readFileSync(backendReqsFile, 'utf8');
  fs.writeFileSync(netlifyReqsFile, reqsContent, 'utf8');
  fs.writeFileSync(rootReqsFile, reqsContent, 'utf8');
  console.log('  ✔ Synchronized requirements.txt from backend/requirements.txt');
} else {
  console.error('  ✖ Error: backend/requirements.txt not found!');
  process.exit(1);
}

// 3. Helper to recursively copy directories while ignoring __pycache__ and sensitive files
function copyDirRecursive(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }

  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    // Skip cache and sensitive files
    if (
      entry.name === '__pycache__' ||
      entry.name.endsWith('.pyc') ||
      entry.name.endsWith('.pyo') ||
      entry.name.endsWith('.db') ||
      entry.name.endsWith('.sqlite') ||
      entry.name === '.env' ||
      entry.name === '.pytest_cache'
    ) {
      continue;
    }

    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

// 4. Copy backend/app into netlify/functions/app
if (fs.existsSync(backendAppDir)) {
  copyDirRecursive(backendAppDir, netlifyAppDir);
  console.log('  ✔ Packaged backend/app into netlify/functions/app');
} else {
  console.error('  ✖ Error: backend/app directory not found!');
  process.exit(1);
}

console.log('✅ [MailMind Netlify Packager] Netlify deployment preparation complete.');
