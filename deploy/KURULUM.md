# Kendi sunucuya taşıma (sabit IP)

Neden: Render'ın çıkış IP'si başka servislerle paylaşılıyor → Binance IP engelleri (418 / -1003) ve IP değişince -2015.
Kendi sunucunun IP'si sadece bizim ve değişmez.

## 1. Sunucu (bir kez)
- Hetzner Cloud (ya da benzeri) → yeni sunucu: **Ubuntu 24.04**, en küçük paket (2 CPU / 4 GB, ~4-6 €/ay), konum **Almanya / Finlandiya**
  (ABD olmasın: Binance ABD IP'lerini engeller).
- SSH anahtarı yoksa root şifresi e-postayla gelir. Telefondan bağlanmak için: Termius uygulaması ya da sağlayıcının web konsolu.

## 2. GitHub okuma anahtarı (bir kez)
- GitHub → Settings → Developer settings → Fine-grained tokens → Generate: Repository = sapan-bot, Permissions → Contents: **Read-only**.
- Çıkan `github_pat_...` değerini kopyala.

## 3. Kurulum (sunucuda, root)
```
git clone https://TOKEN@github.com/hazargn0367-jpg/sapan-bot.git /opt/sapan-bot
bash /opt/sapan-bot/deploy/kurulum.sh
nano /etc/sapan-bot.env
```
`/etc/sapan-bot.env`'e Render → Environment'taki değerleri yaz (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BINANCE_API_KEY, BINANCE_API_SECRET, varsa diğerleri).

## 4. Geçiş (açık işlem / bekleyen emir YOKKEN)
1. Render → keskin-nisanci-bot → **Suspend** (iki bot aynı anda çalışırsa emirler iki kez konur, Telegram karışır).
2. Sunucuda: `systemctl start sapan-bot`
3. Telegram: `/ip` → çıkan IP'yi Binance API Management → trusted IPs'e ekle → `/oto` (bakiye görünmeli) → `/oto aç` → `/durum`.

Not: Render diskindeki günlük / otomatik işlem geçmişi taşınmaz (son 24 saat çarpanı 1x'ten başlar, "son 30 gün" sıfırlanır).

## Güncellemeler
`deploy/guncelle.sh` 2 dakikada bir GitHub `main` dalına bakar, yeni commit varsa çekip botu yeniden başlatır (Render'daki gibi:
"yükle" = main'e gönderme). Elle: `bash /opt/sapan-bot/deploy/guncelle.sh`. Kayıtlar: `journalctl -u sapan-bot -f`.
Durdurma: `systemctl stop sapan-bot` · başlatma: `systemctl start sapan-bot`.
