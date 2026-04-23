<?php
// Rosepith WhatsApp Webhook Handler
// Meta Business API webhook doğrulama ve mesaj alma

define('VERIFY_TOKEN', 'rosepith_webhook_2026');
define('ACCESS_TOKEN', 'EAAlKIK79bnYBRcaRWZCaGqHBCfD6giZCELHMo8zIf60tL5uRb3I0uRpOJem5BbwZAptCpEdVc0kZAvYDZBl8InZBWZClIDaPZAqhzJfweY4Lg1dyZAHCSENvCPxRKMgIWcK9tBnAp56kVUroq6ySmF2FAlTI1yoZBmdzxWNmukV1ikBZA0ZB2hDZAoaPCDX8l5FfFjqc5ddqDAiUB4ugUjgsShZCUGtH0ScVhuSGeUoHe2j2WiILPmQLlbe8TQ8VXt55HsR9azwUYlXOrcgSo7un1ntooZAL22IE7zW7bpsMQZDZD');
define('PHONE_NUMBER_ID', '1059184707283584');
define('LOG_FILE', __DIR__ . '/../logs/webhook.log');
define('TELEGRAM_TOKEN', '8532355893:AAHyoafvS0lanBaj9FFtNT16fUy2UMJ7M3c');
define('TELEGRAM_CHAT_ID', '8694241923');

header('Content-Type: application/json');
header('ngrok-skip-browser-warning: true');

// GET — Meta webhook doğrulama
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    $mode      = $_GET['hub_mode']         ?? $_GET['hub.mode']         ?? '';
    $token     = $_GET['hub_verify_token'] ?? $_GET['hub.verify_token'] ?? '';
    $challenge = $_GET['hub_challenge']    ?? $_GET['hub.challenge']    ?? '';

    if ($mode === 'subscribe' && $token === VERIFY_TOKEN) {
        log_event('Webhook doğrulandı');
        http_response_code(200);
        echo $challenge;
        exit;
    }
    http_response_code(403);
    echo json_encode(['error' => 'Doğrulama başarısız']);
    exit;
}

// POST — Gelen mesajları işle
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $raw     = file_get_contents('php://input');
    $payload = json_decode($raw, true);

    if (!$payload || ($payload['object'] ?? '') !== 'whatsapp_business_account') {
        http_response_code(200);
        echo json_encode(['status' => 'ignored']);
        exit;
    }

    $messages = parse_messages($payload);
    foreach ($messages as $msg) {
        log_event("Mesaj: {$msg['from']} -> {$msg['text']}");
        mark_as_read($msg['id']);
        forward_to_telegram($msg);
    }

    http_response_code(200);
    echo json_encode(['status' => 'ok']);
    exit;
}

http_response_code(405);
echo json_encode(['error' => 'Method not allowed']);


// --- Yardımcı Fonksiyonlar ---

function parse_messages(array $payload): array {
    $messages = [];
    foreach ($payload['entry'] ?? [] as $entry) {
        foreach ($entry['changes'] ?? [] as $change) {
            $value = $change['value'] ?? [];
            foreach ($value['messages'] ?? [] as $msg) {
                $messages[] = [
                    'from'      => $msg['from'] ?? '',
                    'id'        => $msg['id'] ?? '',
                    'timestamp' => $msg['timestamp'] ?? '',
                    'type'      => $msg['type'] ?? '',
                    'text'      => ($msg['type'] === 'text') ? ($msg['text']['body'] ?? '') : "[{$msg['type']}]",
                    'name'      => $value['contacts'][0]['profile']['name'] ?? $msg['from'] ?? '',
                ];
            }
        }
    }
    return $messages;
}

function mark_as_read(string $message_id): void {
    if (!$message_id) return;
    $url = 'https://graph.facebook.com/v19.0/' . PHONE_NUMBER_ID . '/messages';
    send_request($url, ['messaging_product' => 'whatsapp', 'status' => 'read', 'message_id' => $message_id]);
}

function forward_to_telegram(array $msg): void {
    $text = "📱 *WhatsApp Mesajı*\n"
          . "*Gönderen:* {$msg['name']} (+{$msg['from']})\n"
          . "*Mesaj:* {$msg['text']}";
    $url = "https://api.telegram.org/bot" . TELEGRAM_TOKEN . "/sendMessage";
    send_request($url, [
        'chat_id'    => TELEGRAM_CHAT_ID,
        'text'       => $text,
        'parse_mode' => 'Markdown',
    ]);
}

function send_request(string $url, array $data): array {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => json_encode($data),
        CURLOPT_HTTPHEADER     => [
            'Content-Type: application/json',
            'Authorization: Bearer ' . ACCESS_TOKEN,
        ],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 10,
    ]);
    $resp = curl_exec($ch);
    curl_close($ch);
    return json_decode($resp, true) ?? [];
}

function log_event(string $message): void {
    $dir = dirname(LOG_FILE);
    if (!is_dir($dir)) @mkdir($dir, 0755, true);
    $line = date('Y-m-d H:i:s') . ' [webhook] ' . $message . PHP_EOL;
    @file_put_contents(LOG_FILE, $line, FILE_APPEND | LOCK_EX);
}
