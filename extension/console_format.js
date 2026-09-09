// Turning CDP Runtime.consoleAPICalled args back into a console line.
//
// Its own module so it can be tested without booting the service worker (which
// registers webRequest listeners on import).



/** CDP RemoteObject -> a short string, close to what the console shows. */
export function renderArg(arg) {
  if (!arg) return '';
  if (arg.type === 'string') return arg.value;
  if ('value' in arg) {
    if (arg.value === null || typeof arg.value !== 'object') return String(arg.value);
    try { return JSON.stringify(arg.value); } catch (e) { return arg.description || '[object]'; }
  }
  if (arg.unserializableValue) return arg.unserializableValue;
  return arg.description || arg.type || '';
}

/**
 * The scripts style their DONE/FAILED lines with %c, e.g.
 *   console.log('%cDONE. Created journey IDs:', 'color:#22c55e', realIds)
 * Naively joining the args prints the CSS. Consume one arg per %c, keep the
 * rest — %s/%d/%o are substituted the same way.
 */
export function formatConsoleArgs(args) {
  if (!args.length) return '';
  const first = args[0];
  // %% is in the set so an escaped percent collapses the same way whether or
  // not the line also carries a real directive.
  if (first.type !== 'string' || !/%[csdifoO%]/.test(first.value || '')) {
    return args.map(renderArg).filter(Boolean).join(' ');
  }
  let i = 1;
  const text = String(first.value).replace(/%([csdifoO%])/g, (whole, kind) => {
    if (kind === '%') return '%';
    const arg = args[i];
    if (arg === undefined) return whole;
    i += 1;
    // %c is a style directive: swallow the CSS, emit nothing.
    return kind === 'c' ? '' : renderArg(arg);
  });
  const rest = args.slice(i).map(renderArg).filter(Boolean);
  return [text.trim(), ...rest].filter(Boolean).join(' ');
}
