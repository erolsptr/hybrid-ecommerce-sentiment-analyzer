import pandas as pd
from sklearn.model_selection import train_test_split
from datasets import Dataset, DatasetDict
from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer
import numpy as np
import evaluate
import torch

# --- VERİYİ HAZIRLAMA ---
print("Adım 1: Etiketlenmiş veri okunuyor ve hazırlanıyor...")
try:
    df = pd.read_json('etiketler.json')
except Exception as e:
    print(f"HATA: etiketler.json dosyası okunamadı. Hata: {e}")
    exit()

data_list = []
for index, row in df.iterrows():
    yorum_metni = row['yorum_metni']
    for etiket in row['etiketler']:
        konu = etiket['konu']
        duygu = etiket['duygu']
        label_map = {"Pozitif": 2, "Nötr": 1, "Negatif": 0}
        label_id = label_map.get(duygu)
        if label_id is not None:
            data_list.append({
                'text': konu,
                'text_pair': yorum_metni,
                'label': label_id
            })

processed_df = pd.DataFrame(data_list)
train_df, test_df = train_test_split(processed_df, test_size=0.2, random_state=42)
train_dataset = Dataset.from_pandas(train_df)
test_dataset = Dataset.from_pandas(test_df)
raw_datasets = DatasetDict({
    'train': train_dataset,
    'test': test_dataset
})
print(f"Veri hazır! Toplam {len(processed_df)} etiket bulundu.")
print(f"Eğitim için {len(train_dataset)} örnek, test için {len(test_dataset)} örnek ayrıldı.")


# --- MODELİ VE TOKENIZER'I YÜKLEME ---
print("\nAdım 2: Temel BERT modeli ve tokenizer yükleniyor...")
model_checkpoint = "savasy/bert-base-turkish-sentiment-cased"
tokenizer = AutoTokenizer.from_pretrained(model_checkpoint)

def tokenize_function(examples):
    return tokenizer(examples["text"], examples["text_pair"], truncation=True, max_length=512)

tokenized_datasets = raw_datasets.map(tokenize_function, batched=True)
print("Veri seti tokenize edildi.")
tokenized_datasets = tokenized_datasets.remove_columns(["text", "text_pair", "__index_level_0__"])
tokenized_datasets = tokenized_datasets.rename_column("label", "labels")
tokenized_datasets.set_format("torch")

model = AutoModelForSequenceClassification.from_pretrained(
    model_checkpoint, 
    num_labels=3,
    ignore_mismatched_sizes=True 
)


# --- EĞİTİM SÜRECİ ---
print("\nAdım 3: Eğitim süreci yapılandırılıyor...")

metric = evaluate.load("accuracy")
def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    return metric.compute(predictions=predictions, references=labels)

training_args = TrainingArguments(
    output_dir="yeni_modelim",
    num_train_epochs=3,
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    weight_decay=0.01,
    logging_dir='./logs',
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_datasets["train"],
    eval_dataset=tokenized_datasets["test"],
    tokenizer=tokenizer,
    compute_metrics=compute_metrics,
)

print("\n--- EĞİTİM BAŞLIYOR! ---")
print("Bu işlem uzun sürebilir. Lütfen sabırla bekleyin...")

trainer.train()

print("\n--- EĞİTİM SONRASI DEĞERLENDİRME ---")
eval_results = trainer.evaluate()
print(f"Son Değerlendirme Sonuçları: {eval_results}")

print("\n--- EN İYİ MODEL KAYDEDİLİYOR ---")
trainer.save_model("yeni_modelim/best")

print("\n--- EĞİTİM TAMAMLANDI! ---")
print("En iyi model 'yeni_modelim/best' klasörüne kaydedildi.")