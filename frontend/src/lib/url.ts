/**
 * Client-side pre-check for a better form experience. It is NOT a security control:
 * the API re-validates every submission (DNS, public-address and port rules).
 */
export function precheckAuditUrl(raw: string): { ok: true; url: string } | { ok: false; message: string } {
  const text = raw.trim();
  if (!text) return { ok: false, message: "Enter a website address." };
  if (text.length > 2048) return { ok: false, message: "That address is too long." };
  if (/\s/.test(text)) return { ok: false, message: "Addresses cannot contain spaces." };
  if (!text.includes("://") && /^[a-z][a-z0-9+.-]*:(?!\d)/i.test(text)) {
    return { ok: false, message: "Only http:// and https:// addresses can be audited." };
  }
  const withScheme = text.includes("://") ? text : `https://${text}`;
  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    return { ok: false, message: "That does not look like a valid web address." };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { ok: false, message: "Only http:// and https:// addresses can be audited." };
  }
  if (url.username || url.password) return { ok: false, message: "Remove the username or password from the address." };
  const host = url.hostname.replace(/\.$/, "").toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local")) {
    return { ok: false, message: "Local network addresses cannot be audited." };
  }
  if (!host.includes(".") && !host.startsWith("[")) {
    return { ok: false, message: "Use a full public domain name, such as example.com." };
  }
  url.hash = "";
  return { ok: true, url: url.toString() };
}
