# Tralala

İş yoldaşları üçün canlı viktorina platforması. Öz kompüterində işləyir, oyunçular telefonla QR kodu skan edib qoşulur. Otaqda ən çox 30 nəfər ola bilər.

## Başlatmaq

```bash
.venv/Scripts/python main.py
```

Aparıcı paneli: <http://localhost:8020/admin>. Oyunçuların ünvanı konsolda və səhnədə görünür.

Oyun telefonda oynanılır: sual, variantlar, şəkil və video, kimin nə seçdiyi, ən yaxşı beşlik və turnir cədvəli hər oyunçunun öz telefonunda görünür. Səhnə (`/stage`) aparıcının idarə panelidir, projektor lazım deyil.

Hamı eyni Wi-Fi şəbəkəsində olmalıdır. Telefon açılmırsa, Wi-Fi-da cihazların bir-birini görməsi bağlı ola bilər (qonaq şəbəkələrində çox olur). Səhnədəki ünvan səhvdirsə, `.env` faylında `TRALALA_LAN_IP` yazın.

## AI izahçısı

Suallar AI ilə yazılmır, onları özümüz hazırlayırıq. AI (Groq, `openai/gpt-oss-120b`) başqa işdə kömək edir: cavab açılandan sonra oyunçu telefonda "Niyə belədir? AI-dan soruş" düyməsinə basır və ya öz sualını yazır, AI düzgün cavabın səbəbini 2–4 cümlə ilə izah edir. Oyun bitəndə bütün suallar siyahı şəklində görünür və istənilən sual haqqında soruşmaq olar. Cavabı açılmamış sual haqqında soruşmaq olmur, hər oyunçu bir oyunda ən çox 20 sual verə bilər. AI sualın kontekstini və aparıcının izahını görür, amma rəqəmlərdə yanıla bilər.

Açar `.env` faylında `GROQ_API_KEY` kimi saxlanılır. Groq açarı yoxdursa və `ANTHROPIC_API_KEY` yazılıbsa, Claude işlənir.

## AI zarafatları

Cavab açılandan 2–4 saniyə sonra hər oyunçunun telefonuna onun nəticəsinə uyğun zarafatlı bir cümlə gəlir: sürətə, ardıcıl düz cavablara, yer dəyişməsinə və səhvlərə görə. Oyun bitəndə hər kəs zarafatlı bir "titul" alır. Bütün oyunçuların şərhi hər sual üçün tək Groq sorğusu ilə yazılır, ona görə 20 nəfərlə də limit dolmur. Aparıcı lobbidə "Zarafatsız" seçib bunu söndürə bilər. AI cavab verməsə, oyun dayanmır, sadəcə şərh görünmür.

Model yalnız oyun haqqında zarafat etməlidir: görünüş, cins, yaş və s. qadağandır. Cinsə işarə edən sözləri olan sətirlər avtomatik atılır. Groq-un Azərbaycan dili mükəmməl deyil: hərdən yöndəmsiz ifadə və ya kiçik faktiki yanlışlıq olur (məsələn, saniyə əvəzinə dəqiqə).

## Oyunçunun ID-si

Oyunçu adla yox, telefonunun daimi ID-si ilə tanınır. QR kodu ilk dəfə oxudanda ad yazır, sonrakı oyunlara ad yazmadan qoşulur. Reytinq, turnir və çempionluqlar ID ilə hesablanır, ona görə başqasının adı ilə qoşulub xal toplamaq olmur. Ad oyun başlamazdan əvvəl telefonda dəyişdirilə bilər, xallar itmir. Brauzerin məlumatlarını silmək, başqa telefon və ya başqa brauzer yeni ID deməkdir.

## Hazır viktorinalar

`viktorinalar/` qovluğundakı hər `.json` faylı server açılanda panelə avtomatik düşür, idxal etməyə ehtiyac yoxdur. Paneldə viktorinanın yanındakı **Oyna** düyməsi oyunu başladır. Paneldə eyni adlı viktorina artıq varsa, fayl ona toxunmur, ona görə paneldə etdiyiniz dəyişikliklər itmir. Viktorinanı birdəfəlik silmək üçün faylını da qovluqdan silin. Faylda səhv varsa, server konsolda xəbərdarlıq yazır və həmin faylı keçir.

Paneldəki "Fayldan əlavə et" düyməsi eyni formatda faylı əl ilə əlavə edir, viktorinanın "JSON" düyməsi onu fayl kimi yükləyir.

Bu repoda yalnız `sinaq-oyunu.json` var: hər sual tipini göstərən nümunə. Həqiqi
viktorinalar paneldə yazılır və `data/` qovluğunda qalır, repoya düşmür.

## İmkanlar

- 8 sual tipi: tək seçim, çox seçim, doğru/yanlış, yazılı cavab, şkala, ardıcıllıq, sorğu, söz buludu
- Fərdi və komanda rejimi (komanda xalı üzvlərin ortalamasıdır)
- Sualda şəkil və ya video: əvvəlcə hər telefonda yalnız media göstərilir (şəkil 6 saniyə, video səhnədə bitənə qədər), sonra sual açılır. Aparıcı “Suala keç” ilə tez keçə bilər. Telefon səsli avtomatik oynatmanı bloklasa, video səssiz başlayır və “Səsi aç” düyməsi çıxır. Şəkil 10 MB-a, video (MP4, WEBM) 50 MB-a qədər: hər telefon videonu ayrıca yükləyir, 20 telefonla 50 MB-lıq video Wi-Fi-dan 1 GB keçirir, ona görə qısa və yüngül videolar seçin.
- Əl ilə və avtomatik gediş, 2× xal, seriya bonusu
- Aparıcının xal düzəlişi: oyun başlayandan sonra səhnənin yuxarısındakı "Xallar" düyməsi istənilən oyunçunun xalını silməyə (istənilən miqdar və ya "Sıfırla"), səhvən silinəni geri qaytarmağa imkan verir. İstəyə bağlı səbəb yazılır, oyunçunun telefonuna bildiriş gedir, düzəliş hesabatda və CSV-də görünür. Oyun bitəndən sonra edilən düzəliş nəticəni və reytinqi də yeniləyir. Turnir duellərində də işləyir. Panel yalnız aparıcının kompüterindədir.
- Daimi reytinq: həftəlik və ümumi cədvəl, nişanlar
- Turnir (pley-off): iştirakçılar telefonla yazılır, püşk atılır, hər kəs cüt-cüt qarşılaşır. Qalib növbəti raunda keçir, uduzan çıxır. Duellər bir-bir oynanılır, qalanlar gedən duelin sualını, hesabını və cədvəli öz telefonunda izləyir, hər dueldə 1, 3, 5 və ya 7 sual olur. Bərabərlikdə 3-ə qədər əlavə sual verilir, sonra daha çox düz cavab, daha sürətli cavab, ən sonda püşk həll edir. Rəqib gəlməyibsə, aparıcı texniki qələbə verir. Turnir hər dueldən sonra yadda saxlanılır, sonra "Səhnəni aç" ilə davam etdirmək olar. Çempionlar reytinqdə "Turnir çempionu" nişanı alır.
- Hər oyun üçün hesabat və Excel üçün CSV
- Telefon bağlantısı kəsiləndə oyunçu xalını itirmədən qayıdır

## Bilməli olduqların

- İdarəetmə (panel, səhnə, API) yalnız serverin işlədiyi kompüterdən açılır.
- Reytinqdə oyunçular telefonun ID-si ilə tanınır (yuxarıya bax).
- Canlı oyun yaddaşda saxlanır. Server oyun ortasında dayansa, həmin oyun itir. Bitmiş oyunlar `data/tralala.db` faylındadır.
- Sınaq oyununu Hesabatlar bölməsindən silmək olar, xalları reytinqdən də çıxır.

## Testlər

```bash
.venv/Scripts/python -m pytest tests
```

```bash
.venv/Scripts/python tests/load_20.py
```

İkinci əmr işləyən serverdə 20 eyni vaxtlı oyunçu ilə tam oyun keçirir və nəticəsini reytinqə yazır, sonra onu Hesabatlardan silin.
