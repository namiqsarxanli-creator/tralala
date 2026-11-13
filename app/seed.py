"""Hər sual tipini göstərən nümunə viktorina. Testlər və yük sınağı istifadə edir, bazaya özü yazılmır."""
from .questions import clean_question

SAMPLE = [
    {"type": "choice", "text": "Azərbaycanın paytaxtı hansı şəhərdir?", "time": 15,
     "options": ["Gəncə", "Bakı", "Şəki", "Lənkəran"], "correct": [1]},
    {"type": "truefalse", "text": "Xəzər dünyanın ən böyük qapalı su hövzəsidir.", "time": 15, "correct": [0]},
    {"type": "multi", "text": "Bunlardan hansılar proqramlaşdırma dilidir?", "time": 20,
     "options": ["Python", "Rust", "Photoshop", "Go"], "correct": [0, 1, 3]},
    {"type": "text", "text": "“Odlar yurdu” adlanan ölkə hansıdır?", "time": 20, "accepted": ["Azərbaycan"]},
    {"type": "slider", "text": "Bir ildə təxminən neçə həftə var?", "time": 20,
     "min": 40, "max": 60, "step": 1, "answer": 52, "tolerance": 0},
    {"type": "order", "text": "Planetləri Günəşə yaxınlığına görə düz.", "time": 25,
     "options": ["Merkuri", "Venera", "Yer", "Mars"]},
    {"type": "poll", "text": "Səhər çay, yoxsa qəhvə?", "time": 15, "options": ["Çay", "Qəhvə", "Hər ikisi"]},
    {"type": "cloud", "text": "Ofisimizi bir sözlə təsvir et.", "time": 20},
]

