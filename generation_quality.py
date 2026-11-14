"""Deterministic generation constraints. No generation, edits or paid retries."""
import argparse
import json
from pathlib import Path


def prepare_prompt(prompt, kind, negative_prompt=None):
    if kind not in ('image','video') or not isinstance(prompt,str) or not prompt.strip():
        raise ValueError('QUALITY_PROMPT_INVALID')
    instructions = ['When depicting ordinary humans, preserve anatomically natural hands: five total fingers per fully visible hand, no extra/fused digits or limbs. Prefer simple stable gestures and natural occlusion; do not force hidden fingers into view. Honor explicitly requested nonhuman or stylized anatomy.']
    if negative_prompt is not None:
        if not isinstance(negative_prompt, str) or not negative_prompt.strip():
            raise ValueError('QUALITY_NEGATIVE_PROMPT_INVALID')
        instructions.append('Avoid in the generated scene: ' + negative_prompt.strip())
    if kind == 'video' and '小程序' in prompt:
        instructions.append('Spoken Mandarin term: 小程序 = xiǎo chéng xù (xiao3 cheng2 xu4). Pronounce 程 chéng and 序 xù distinctly. Speak only the intended Chinese dialogue; never read the pronunciation notes aloud. Keep subtitle spelling 小程序 unchanged.')
    return prompt + '\n\nGeneration quality constraints (not spoken dialogue):\n' + '\n'.join(instructions)

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=['image','video'],required=True)
    parser.add_argument('--prompt-file',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps({'prompt':prepare_prompt(args.prompt_file.read_text(encoding='utf-8'),args.kind),
                      'requires_visual_review':True,'pronunciation_guaranteed':False},ensure_ascii=False))
