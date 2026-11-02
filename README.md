# Techburin Construct — Telegram avtopost

«Claude maslahatlar» rubrikasi uchun postlarni o‘zi tayyorlab, siz tasdiqlagach kanalga chiqaradigan tizim.

## Qanday ishlaydi

| Agent | Vazifasi |
|---|---|
| 1. Mavzu | Gemini + Google qidiruvi orqali rubrikaga mos yangi mavzu topadi, oldingilarini takrorlamaydi |
| 2. Matn | Mavzu bo‘yicha internetdan ma’lumot yig‘adi va postni sizning stilingizda yozadi |
| 3. Rasm | Nano Banana orqali real foto ko‘rinishidagi rasm yaratadi, logoni burchakka qo‘yadi |
| 4. Audio | ElevenLabs orqali qisqa ovozli maslahat (30–45 soniya) tayyorlaydi |
| 5. Nazorat | Narx, raqobatchi, manbasiz raqam, imlo va uzunlikni tekshiradi; o‘tmasa 2 marta qayta yozdiradi |
| 6. Chiqarish | Qoralamani sizga Telegram'da yuboradi, tasdiqlasangiz belgilangan vaqtda kanalga chiqaradi |
| 7. Video | Kartochka, ovozli maslahat va subtitrdan 30–45 soniyalik video yig‘adi (bepul) |

**Jadval:** Dushanba, Chorshanba, Juma soat 09:00 (Toshkent). Qoralama bir kun oldin kechqurun (19:00–20:00 atrofida) keladi.

Har bir qoralama tagida tugmalar bor:
- ✅ **Vaqtida chiqarish** — belgilangan vaqtda chiqadi
- 🚀 **Hozir chiqarish** — keyingi tekshiruvda darhol chiqadi
- 🔁 **Qayta yozish** — yangi mavzu bilan boshqa qoralama tayyorlanadi
- ❌ **Bekor qilish** — bu vaqtga post chiqmaydi

Tizim har 30 daqiqada tekshiradi, shuning uchun tugma bosilgandan keyin natija 30 daqiqa ichida ko‘rinadi.

Botga yozish mumkin bo‘lgan buyruqlar: `/yangi` (hozir yangi qoralama), `/holat` (navbatdagi postlar).

---

## O‘rnatish (bir marta, ~15 daqiqa)

### 1. GitHub'da repo oching
1. github.com'ga kiring → yuqori o‘ngdagi **+** → **New repository**.
2. Nomi: `techburin-autopost`, turi: **Private**. **Create repository** bosing.

### 2. Fayllarni yuklang
1. Repo sahifasida **uploading an existing file** havolasini bosing.
2. ZIP ichidagi `techburin-autopost` papkasini oching va ichidagi **hamma narsani** (`.github`, `autopost`, `assets`, `state`, `config.yaml`, `requirements.txt`, `README.md`) sahifaga sudrab tashlang.
3. **Commit changes** bosing.

> `.github` papkasi ko‘rinmasa (Mac'da yashirin bo‘ladi): Finder'da **Cmd + Shift + .** bosing.
> Yoki repo'da **Add file → Create new file** bosib, nomiga `.github/workflows/autopost.yml` yozing va shu faylning ichidagi matnni joylang.

### 3. Logoni qo‘shing
`assets` papkasiga logongizni **`logo.png`** nomi bilan yuklang (shaffof fonli PNG yaxshi). Logo bo‘lmasa, rasm logosiz chiqadi.

### 4. Kalitlarni kiriting
Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Uchta secret qo‘shing:

| Name | Qiymati |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather bergan **yangi** token |
| `GEMINI_API_KEY` | Google AI Studio kaliti |
| `ELEVENLABS_API_KEY` | ElevenLabs kaliti |

Kalitlarni boshqa hech qayerga yozmang.

### 5. Botni ishga tushiring
Telegram'da o‘z botingizni oching va **Start** tugmasini bosing. Busiz bot sizga qoralama yubora olmaydi.
Bot kanalda admin va «Xabarlarni joylash» ruxsati yoqilgan bo‘lishi kerak.

### 6. Tekshiring
Repo → **Actions** → chapda **Techburin avtopost** → **Run workflow** → `tekshirish` → **Run workflow**.
1–2 daqiqadan keyin bot sizga hisobot yuboradi. Hammasi ✅ bo‘lishi kerak.

### 7. Ovozni tanlang
Xuddi shu yerdan `ovozlarni-sinash` ni ishga tushiring. Bot 6 ta ovoz namunasini yuboradi.
Yoqqanining `voice_id` sini nusxalang → repo'da `config.yaml` ni oching → qalam belgisi → `voice_id: ""` qatoriga yozing → **Commit changes**.

### 8. Birinchi post
`yangi-post` ni ishga tushiring. 5–10 daqiqada birinchi qoralama keladi. Ko‘rib chiqing va tugmalardan birini bosing.

Shundan keyin tizim o‘zi ishlaydi.

---

## Sozlamalarni o‘zgartirish
Hammasi `config.yaml` faylida: kunlar, vaqt, telefon, xeshteglar, taqiqlar, rasm uslubi, ovoz.
GitHub'da faylni ochib, qalam belgisi bilan tahrirlang va **Commit changes** bosing. Keyingi tekshiruvdan boshlab kuchga kiradi.

**To‘liq avtomatik rejimga o‘tish:** sifat barqaror bo‘lgach, `mode: approval` ni `mode: auto` ga o‘zgartiring.
Shunda nazoratdan o‘tgan postlar tasdiqsiz chiqadi, o‘tmaganlari baribir sizga keladi.

## Video
Har bir qoralama bilan birga video ham keladi: kartochka sekin yaqinlashadi, pastda ovozga mos subtitr chiqadi,
oxirida 2 soniya telefon raqami ko‘rinadi. Kanalga rasm, ovoz va video ketma-ket chiqadi.
Sozlamalar `config.yaml` → `video` bo‘limida: o‘chirish (`enabled: false`), format (`4:5` yoki Reels uchun `9:16`).
Video tayyorlanmay qolsa ham post to‘xtamaydi: rasm va ovoz odatdagidek chiqadi, qoralamada eslatma ko‘rinadi.

## Bepul rejim va to‘liq rejim
Hozir tizim **bepul rejimda** ishlaydi (`config.yaml`):
- `features.web_search: false`: mavzu va maslahat Gemini'ning o‘z bilimidan yoziladi, aniq raqamlar ishlatilmaydi.
- `image.mode: card`: AI rasm o‘rniga brend kartochka (sarlavha, logo, telefon) chiziladi.
  `assets/photos` papkasiga obyekt rasmlarini yuklasangiz, kartochka shu rasmlar ustiga chiziladi.

**To‘liq rejimga o‘tish:** Google AI Studio'da billing yoqing, keyin `config.yaml` da
`web_search: true` va `mode: ai` qiling. Shunda internetdan izlash va Nano Banana rasmlari ishlaydi
(taxminan oyiga $1–2).

## Xarajatlar
- **GitHub:** bepul. Tizim oyiga taxminan 1100 daqiqa ishlatadi, private repo uchun bepul limit 2000 daqiqa.
- **Gemini:** rasm yaratish pullik bo‘lishi mumkin; AI Studio'da billing yoqing va limit qo‘ying.
- **ElevenLabs:** biznes kanal uchun kommersiya litsenziyali tarif kerak (Starter yoki yuqori).

## Muammolar

| Belgi | Yechim |
|---|---|
| Actions'da `TELEGRAM_BOT_TOKEN topilmadi` | 4-qadamdagi secret nomini tekshiring (katta harflar, bo‘sh joysiz) |
| Bot hech narsa yubormayapti | Botda **Start** bosilganini va `config.yaml` dagi `admin_chat_id` to‘g‘riligini tekshiring |
| `bot admin emas` | Kanal → Administratorlar → botni qo‘shing, «Xabarlarni joylash»ni yoqing |
| `Holatni saqlash` qadamida `403` xato | Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save |
| Gemini `404` yoki `model not found` | `config.yaml` → `models` bo‘limidagi model nomini AI Studio'dagi mavjud model bilan almashtiring |
| Ovoz yomon talaffuz qilyapti | 7-qadamdagi namunalardan boshqa ovoz tanlang |
| Jadval bo‘yicha ishga tushmayapti | Actions bo‘limida workflow yoqilganini tekshiring (60 kun faoliyatsiz qolsa, GitHub o‘chirib qo‘yadi) |
