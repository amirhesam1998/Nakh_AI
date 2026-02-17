# -*- coding: utf-8 -*-

import os
os.environ['PYOPENGL_PLATFORM'] = 'egl'  # جلوگیری از خطاهای EGL روی ویندوز یا سرور

import sys
import cv2
import time
import joblib
import argparse
from loguru import logger

sys.path.append('.')
from pare.core.tester import PARETester
from pare.utils.demo_utils import (
    download_youtube_clip,
    video_to_images,
    images_to_video,
)

CFG = 'data/pare/checkpoints/pare_w_3dpw_config.yaml'
# CFG = '.\AI_Processing\PARE\data\pare\checkpoints\pare_w_3dpw_config.yaml'
# CKPT = '.\AI_Processing\PARE\data\pare\checkpoints\pare_w_3dpw_checkpoint.ckpt'
CKPT = 'data/pare/checkpoints/pare_w_3dpw_checkpoint.ckpt'
MIN_NUM_FRAMES = 0


def main(args):

    demo_mode = args.mode
    output_path = None

    # ================== VIDEO MODE ==================
    if demo_mode == 'video':
        video_file = args.vid_file

        if video_file is None or str(video_file).strip() == "":
            logger.info("No video file provided. Skipping video processing...")
            demo_mode = 'folder'  # به حالت پوشه برگرد
        else:
            # -------- دانلود از یوتیوب (اختیاری) -------- #
            if isinstance(video_file, str) and video_file.startswith('https://www.youtube.com'):
                logger.info(f'Downloading YouTube video \"{video_file}\"')
                video_file = download_youtube_clip(video_file, '/tmp')

                if video_file is None:
                    exit('Youtube url is not valid!')

                logger.info(f'YouTube Video has been downloaded to {video_file}...')

            if not os.path.isfile(video_file):
                exit(f'Input video \"{video_file}\" does not exist!')

            output_path = os.path.join(
                args.output_folder,
                os.path.basename(video_file).replace('.mp4', '_' + args.exp)
            )
            os.makedirs(output_path, exist_ok=True)

            if os.path.isdir(os.path.join(output_path, 'tmp_images')):
                input_image_folder = os.path.join(output_path, 'tmp_images')
                logger.info(f'Frames already extracted in \"{input_image_folder}\"')
                num_frames = len(os.listdir(input_image_folder))
                img_shape = cv2.imread(os.path.join(input_image_folder, '000001.png')).shape
            else:
                input_image_folder, num_frames, img_shape = video_to_images(
                    video_file,
                    img_folder=os.path.join(output_path, 'tmp_images'),
                    return_info=True
                )

            output_img_folder = f'{input_image_folder}_output'
            os.makedirs(output_img_folder, exist_ok=True)

    # ================== IMAGE FOLDER MODE ==================
    if demo_mode == 'folder':
        args.tracker_batch_size = 1
        input_image_folder = args.image_folder

        if not os.path.isdir(input_image_folder):
            exit(f'Input image folder \"{input_image_folder}\" does not exist!')

        folder_name = os.path.basename(os.path.normpath(input_image_folder))
        output_path = os.path.join(args.output_folder, folder_name + '_' + args.exp)
        os.makedirs(output_path, exist_ok=True)

        output_img_folder = os.path.join(output_path, 'pare_results')
        os.makedirs(output_img_folder, exist_ok=True)

        num_frames = len([f for f in os.listdir(input_image_folder) if f.lower().endswith(('.jpg', '.png'))])

    elif demo_mode == 'webcam':
        logger.error('Webcam demo is not implemented!')
        raise NotImplementedError

    # ================== LOGGER SETUP ==================
    if output_path is None:
        output_path = os.path.join(args.output_folder, 'default_output')
        os.makedirs(output_path, exist_ok=True)

    logger.add(os.path.join(output_path, 'demo.log'), level='INFO', colorize=False)
    logger.info(f'Demo options: \n {args}')

    # ================== LOAD PARE MODEL ==================
    tester = PARETester(args)

    total_time = time.time()

    # ------------------ VIDEO MODE ------------------
    if args.mode == 'video' and video_file:
        logger.info(f'Input video number of frames {num_frames}')
        orig_height, orig_width = img_shape[:2]
        tracking_results = tester.run_tracking(video_file, input_image_folder)
        pare_time = time.time()
        pare_results = tester.run_on_video(tracking_results, input_image_folder, orig_width, orig_height)
        end = time.time()

        fps = num_frames / (end - pare_time)
        del tester.model

        logger.info(f'PARE FPS: {fps:.2f}')
        total_time = time.time() - total_time
        logger.info(f'Total time spent: {total_time:.2f} seconds.')
        logger.info(f'Total FPS (including model loading): {num_frames / total_time:.2f}.')

        if not args.no_save:
            joblib.dump(pare_results, os.path.join(output_path, "pare_output.pkl"))
            logger.info(f'Saved output results to \"{os.path.join(output_path,"pare_output.pkl")}\"')

        if not args.no_render:
            tester.render_results(pare_results, input_image_folder, output_img_folder, output_path,
                                  orig_width, orig_height, num_frames)

            vid_name = os.path.basename(video_file)
            save_name = os.path.join(output_path, f'{vid_name.replace(".mp4", "")}_{args.exp}_result.mp4')
            logger.info(f'Saving result video to {save_name}')
            images_to_video(img_folder=output_img_folder, output_vid_file=save_name)

    # ------------------ FOLDER MODE ------------------
    elif args.mode == 'folder':
        logger.info(f'Number of input images: {num_frames}')

        detections = tester.run_detector(input_image_folder)
        pare_time = time.time()
        # اجرای اینفرنس روی پوشه (این تابع به‌صورت پیش‌فرض چیزی برنمی‌گرداند)
        tester.run_on_image_folder(input_image_folder, detections, output_path, output_img_folder,
                                   run_smplify=args.smplify)
        end = time.time()

        fps = num_frames / (end - pare_time)
        logger.info(f'PARE FPS: {fps:.2f}')
        total_time = time.time() - total_time
        logger.info(f'Total time spent: {total_time:.2f} seconds.')
        logger.info(f'Total FPS (including model loading): {num_frames / total_time:.2f}.')

        # ---------- جمع کردن نتایج و ساخت pare_output.pkl ----------
        # خیلی از فورک‌های PARE خروجی هر فریم را به صورت npz/npz-like داخل output_path می‌ریزند.
        # اگر چیزی نریخته باشد، سعی می‌کنیم از خود tester آبجکت نتایج را بخوانیم.
        import glob
        import numpy as np

        results_pkl = os.path.join(output_path, "pare_output.pkl")

        saved_npzs = sorted(glob.glob(os.path.join(output_path, "*.npz")))
        if saved_npzs:
            logger.info(f"Found {len(saved_npzs)} frame results. Packing to {results_pkl} ...")
            pack = {1: {'verts': [], 'joints3d': [], 'pose': [], 'betas': []}}
            for f in saved_npzs:
                try:
                    d = np.load(f, allow_pickle=True)
                    for k_map in [('vertices', 'verts'), ('joints', 'joints3d'),
                                  ('pose', 'pose'), ('betas', 'betas')]:
                        if k_map[0] in d:
                            pack[1][k_map[1]].append(d[k_map[0]])
                except Exception as e:
                    logger.warning(f"Skip {f}: {e}")

            for k in list(pack[1].keys()):
                if len(pack[1][k]) > 0:
                    pack[1][k] = np.stack(pack[1][k], axis=0)

            joblib.dump(pack, results_pkl)
            logger.info(f"Saved packed results to: {results_pkl}")

        # اگر npz پیدا نشد، تلاش دوم: از خود tester (بعضی نسخه‌ها نتایج را نگه می‌دارند)
        elif hasattr(tester, 'results') and isinstance(tester.results, dict) and tester.results:
            joblib.dump(tester.results, results_pkl)
            logger.info(f"Saved tester.results to: {results_pkl}")

        else:
            logger.warning("⚠️ No per-frame results found to pack. If you only need measurements, "
                           "we can bypass pkl and مستقیماً سه npz بسازیم.")

    logger.info('================= END =================')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--cfg', type=str, default=CFG, help='config file')
    parser.add_argument('--ckpt', type=str, default=CKPT, help='checkpoint path')
    parser.add_argument('--exp', type=str, default='', help='short description of the experiment')

    parser.add_argument('--mode', default='folder', choices=['video', 'folder', 'webcam'],
                        help='Demo type (folder = image folder input)')

    parser.add_argument('--vid_file', type=str, help='input video path or youtube link')
    parser.add_argument('--image_folder', type=str, help='input image folder')
    parser.add_argument('--output_folder', type=str, default='logs/demo/demo_results',
                        help='output folder')

    parser.add_argument('--tracking_method', type=str, default='bbox', choices=['bbox', 'pose'])
    parser.add_argument('--detector', type=str, default='yolo', choices=['yolo', 'maskrcnn'])
    parser.add_argument('--yolo_img_size', type=int, default=416)
    parser.add_argument('--tracker_batch_size', type=int, default=12)
    parser.add_argument('--staf_dir', type=str, default='/home/mkocabas/developments/openposetrack')
    parser.add_argument('--batch_size', type=int, default=16)
    parser.add_argument('--display', action='store_true')
    parser.add_argument('--smooth', action='store_true')
    parser.add_argument('--min_cutoff', type=float, default=0.004)
    parser.add_argument('--beta', type=float, default=1.0)
    parser.add_argument('--no_render', action='store_true')
    parser.add_argument('--no_save', action='store_true')
    parser.add_argument('--wireframe', action='store_true')
    parser.add_argument('--sideview', action='store_true')
    parser.add_argument('--draw_keypoints', action='store_true')
    parser.add_argument('--save_obj', action='store_true')
    parser.add_argument('--smplify', action='store_true')

    args = parser.parse_args()
    main(args)
