import cv2, glob, os

img_dir = r'.\img'                      # پوشه‌ی عکس‌ها
out_mp4 = r'.\img_triplet.mp4'          # خروجی ویدیو
fps = 1                                 # هر عکس = یک فریم (1fps کافی‌ست)

imgs = sorted([p for p in glob.glob(os.path.join(img_dir, '*')) if p.lower().endswith(('.jpg','.png','.jpeg'))])
assert len(imgs) >= 3, "حداقل 3 عکس لازم است."

# خواندن اندازه
frame0 = cv2.imread(imgs[0])
h, w = frame0.shape[:2]
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
wr = cv2.VideoWriter(out_mp4, fourcc, fps, (w, h))
for p in imgs:
    im = cv2.imread(p)
    if im.shape[:2] != (h, w):  # هم‌اندازه‌سازی اختیاری
        im = cv2.resize(im, (w, h))
    wr.write(im)
wr.release()
print("WROTE:", out_mp4, "frames:", len(imgs))
