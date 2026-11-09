/**
 * ResolveAI - send customer emails from your Gmail over HTTPS.
 * Needed when the backend is hosted on a free platform that blocks SMTP (Render, Railway).
 *
 * Setup: script.google.com -> New project -> paste this file -> change SECRET below ->
 * Deploy -> New deployment -> type "Web app" -> Execute as: Me -> Who has access: Anyone ->
 * Deploy -> authorise Gmail -> copy the Web app URL (ends with /exec).
 * Put the URL in GMAIL_WEBHOOK_URL and the same secret in GMAIL_WEBHOOK_SECRET.
 */
const SECRET = 'change-this-to-a-long-random-string';

function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.secret !== SECRET) return reply({ ok: false, error: 'bad secret' });
    if (!d.to || !d.subject || !d.body) return reply({ ok: false, error: 'missing to/subject/body' });
    GmailApp.sendEmail(d.to, d.subject, d.body, { name: 'ResolveAI Support' });
    return reply({ ok: true });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
