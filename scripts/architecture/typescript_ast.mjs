import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const compilerCandidates = [
  path.join(root, 'apps', 'web', 'node_modules', 'typescript', 'lib', 'typescript.js'),
  path.join(root, 'apps', 'desktop_electron', 'node_modules', 'typescript', 'lib', 'typescript.js'),
]
const compilerPath = compilerCandidates.find(candidate => fs.existsSync(candidate))
if (!compilerPath) {
  process.stderr.write(`TypeScript compiler API is unavailable: ${compilerCandidates.join(', ')}\n`)
  process.exit(2)
}
const ts = await import(pathToFileURL(compilerPath).href)

function walk(directory) {
  if (!fs.existsSync(directory)) return []
  const files = []
  for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.name === 'node_modules' || entry.name === 'dist') continue
    const target = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...walk(target))
    else if (/\.(ts|vue)$/.test(entry.name)) files.push(target)
  }
  return files
}

function vueScript(text) {
  const chars = Array.from(text, char => char === '\n' ? '\n' : ' ')
  const pattern = /<script\b[^>]*>([\s\S]*?)<\/script>/gi
  for (const match of text.matchAll(pattern)) {
    const start = match.index + match[0].indexOf(match[1])
    for (let index = 0; index < match[1].length; index += 1) chars[start + index] = match[1][index]
  }
  return chars.join('')
}

function lineOf(source, node) {
  return source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1
}

function functionName(node) {
  if (ts.isFunctionDeclaration(node) && node.name) return node.name.text
  if (ts.isMethodDeclaration(node) && node.name) return node.name.getText()
  if (ts.isVariableDeclaration(node) && node.name && node.initializer && (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) return node.name.getText()
  return null
}

const records = []
for (const file of [...walk(path.join(root, 'apps', 'web', 'src')), ...walk(path.join(root, 'apps', 'desktop_electron', 'src'))]) {
  const original = fs.readFileSync(file, 'utf8')
  const text = file.endsWith('.vue') ? vueScript(original) : original
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const imports = []
  const functions = []
  const legacy = []
  const colors = []
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      imports.push({ specifier: node.moduleSpecifier.text, line: lineOf(source, node) })
    } else if (ts.isCallExpression(node) && node.arguments.length === 1 &&
      ((node.expression.kind === ts.SyntaxKind.ImportKeyword) || (ts.isIdentifier(node.expression) && node.expression.text === 'require')) &&
      ts.isStringLiteral(node.arguments[0])) {
      imports.push({ specifier: node.arguments[0].text, line: lineOf(source, node) })
    }
    const name = functionName(node)
    if (name) functions.push({ name, line: lineOf(source, node) })
    if (ts.isIdentifier(node) && (node.text === 'qt_page_id' || node.text === 'qt_feature_id')) {
      legacy.push({ name: node.text, line: lineOf(source, node) })
    }
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && /^(?:#[0-9a-f]{3,8}|rgba?\(|hsla?\()/i.test(node.text.trim())) {
      colors.push({ value: node.text.trim(), line: lineOf(source, node) })
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  records.push({
    path: path.relative(root, file).split(path.sep).join('/'),
    imports,
    functions,
    legacy,
    colors,
    diagnostics: source.parseDiagnostics.map(item => ({ line: item.start == null ? 0 : source.getLineAndCharacterOfPosition(item.start).line + 1, message: ts.flattenDiagnosticMessageText(item.messageText, ' ') })),
  })
}
process.stdout.write(JSON.stringify(records))
