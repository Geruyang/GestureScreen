"""Extract review-only single-index candidates; never trust source folder direction."""
import argparse
import csv
import hashlib
import io
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Build" / "dataset-hand-detector-deps"))
import cv2
import mediapipe as mp
from PIL import Image, ImageDraw
from import_external_dataset import write_external_frame


def distance(a, b):
    return math.hypot(a.x-b.x,a.y-b.y)


def pointing_label(hand):
    wrist = hand[0]
    if distance(hand[8],wrist) < 1.15*distance(hand[6],wrist):
        return None
    if any(distance(hand[tip],wrist) > 1.12*distance(hand[pip],wrist)
           for tip,pip in ((12,10),(16,14),(20,18))):
        return None
    dx,dy = hand[8].x-hand[5].x,hand[8].y-hand[5].y
    if abs(dx)<.035 or abs(dx)<1.1*abs(dy):
        return None
    return "POINT_RIGHT" if dx>0 else "POINT_LEFT"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--model",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    metadata=list(csv.DictReader((args.root/"metadata.csv").open(encoding="utf-8-sig")))
    options=mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(args.model)),
        num_hands=2,min_hand_detection_confidence=.35,min_hand_presence_confidence=.35)
    rows=[]
    counts=Counter()
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
        for video_index,meta in enumerate(metadata):
            if meta["gesture"] not in ("point_left","point_right"):
                continue
            path=args.root/Path(meta["video_path"].replace("\\","/"))
            capture=cv2.VideoCapture(str(path))
            frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            video_sha=hashlib.sha256(path.read_bytes()).hexdigest()
            for fraction in (.2,.4,.6,.8):
                frame_index=round((frame_count-1)*fraction)
                capture.set(cv2.CAP_PROP_POS_FRAMES,frame_index)
                okay,frame=capture.read()
                if not okay:
                    continue
                rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                result=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb))
                candidates=[(pointing_label(hand),hand) for hand in result.hand_landmarks]
                candidates=[item for item in candidates if item[0]]
                if len(candidates)!=1:
                    continue
                label,hand=candidates[0]
                height,width=rgb.shape[:2]
                left=min(p.x for p in hand)*width
                top=min(p.y for p in hand)*height
                right=max(p.x for p in hand)*width
                bottom=max(p.y for p in hand)*height
                bbox=(left,top,right-left,bottom-top)
                source=io.BytesIO()
                Image.fromarray(rgb).save(source,format="PNG")
                item_id=f'rgb-nhg-v2-{path.stem}-frame-{frame_index}'
                provenance={
                    "dataset":"RGB-NHG smartphone natural gestures","dataset_version":"2",
                    "source_page_url":"https://data.mendeley.com/datasets/n66hhk695h/2",
                    "doi":"10.17632/n66hhk695h.2","source_item_id":item_id,
                    "source_label":meta["gesture"],"subject_id":meta["participant"],
                    "license_spdx":"CC-BY-4.0","license_url":"https://creativecommons.org/licenses/by/4.0/",
                    "attribution":"Tanzeem Rahat, Shahnaj Parvin, Kamruddin Nur (2025)",
                    "mapping_rule_id":"landmark-single-index-horizontal-candidate-only",
                    "video_relative_path":meta["video_path"],"video_sha256":video_sha,
                    "video_frame_index":frame_index,"video_fps":float(meta["fps"]),
                    "source_bbox_xywh":list(bbox),"manual_review_status":"pending",
                }
                row=write_external_frame(args.output,label,"train",f'rgb-nhg-{meta["participant"]}',
                                         source.getvalue(),bbox,provenance,len(rows))
                row["label_provenance"]="automatic_candidate_requires_visual_review"
                originals=args.output/"source_frames"
                originals.mkdir(exist_ok=True)
                (originals/(row["record_id"]+".png")).write_bytes(source.getvalue())
                rows.append(row)
                counts[label]+=1
            capture.release()
            if len(rows)%20==0:
                print(dict(counts),flush=True)
    (args.output/"candidate_rows.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    for start in range(0,len(rows),48):
        sheet=Image.new("RGB",(8*160,6*144),"white")
        draw=ImageDraw.Draw(sheet)
        for index,row in enumerate(rows[start:start+48]):
            x,y=index%8*160,index//8*144
            with Image.open(args.output/row["preview_file"]) as im:
                sheet.paste(im.resize((160,120)),(x,y))
            draw.text((x,y+120),f'{start+index} {row["label"]}',fill="black")
        sheet.save(args.output/f'review-{start//48+1:02d}.jpg')
    print(json.dumps(dict(counts)))


if __name__=="__main__":
    main()
