import joblib, numpy as np, os

# مسیر فایل خروجی PARE (دقیقاً همین مسیر رو بذار)
pkl_path = r'.\src\pre\img_triplet_\pare_output.pkl'

# مسیر خروجی سه فایل npz
out_dir = os.path.dirname(pkl_path)
names = ['tmp_front_smpl.npz', 'tmp_tpose_smpl.npz', 'tmp_side_smpl.npz']

print("Loading:", pkl_path)
data = joblib.load(pkl_path)

# فرض: فقط یک آدم در ویدیو هست
track_id = sorted(data.keys())[0]
verts  = np.asarray(data[track_id]['verts'])
joints = np.asarray(data[track_id]['joints3d'])
pose   = np.asarray(data[track_id]['pose'])
betas  = np.asarray(data[track_id]['betas'])

print("Frames:", len(verts))
assert len(verts) >= 3, "کمتر از سه فریم در ویدیو وجود دارد!"

# ذخیره سه فریم اول (front, arms, side)
for i, name in enumerate(names):
    np.savez(os.path.join(out_dir, name),
             vertices=verts[i],
             joints=joints[i],
             pose=pose[i],
             betas=betas[i])
    print("Wrote:", os.path.join(out_dir, name))
