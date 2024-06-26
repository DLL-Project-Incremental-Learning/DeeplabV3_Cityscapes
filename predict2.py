from torch.utils.data import dataset
from tqdm import tqdm
import network
import utils
import os
import random
import argparse
import numpy as np

from torch.utils import data
from datasets import VOCSegmentation, Cityscapes, cityscapes
from torchvision import transforms as T
from metrics import StreamSegMetrics

import torch
import torch.nn as nn

from PIL import Image
import matplotlib
import matplotlib.pyplot as plt
from glob import glob
from dataloaders import DataProcessor, KITTI360Dataset, DatasetLoader
from weaklabelgenerator import labelgenerator
def get_argparser():
    parser = argparse.ArgumentParser()

    # Datset Options
    parser.add_argument("--bucketidx", type=int, required=True,
                        help="bucket index to use")
    parser.add_argument("--val_data", type=str, required=True, default="False",
                        help="Run predictions on validation data from this file")

    parser.add_argument("--dataset", type=str, default='cityscapes',
                        choices=['voc', 'cityscapes'], help='Name of training set')

    # Deeplab Options
    available_models = sorted(name for name in network.modeling.__dict__ if name.islower() and \
                              not (name.startswith("__") or name.startswith('_')) and callable(
                              network.modeling.__dict__[name])
                              )

    parser.add_argument("--model", type=str, default='deeplabv3plus_resnet101',
                        choices=available_models, help='model name')
    parser.add_argument("--separable_conv", action='store_true', default=False,
                        help="apply separable conv to decoder and aspp")
    parser.add_argument("--output_stride", type=int, default=16, choices=[8, 16])

    # Train Options
    parser.add_argument("--save_val_results_to", default=None,
                        help="save segmentation results to the specified dir")

    parser.add_argument("--crop_val", action='store_true', default=False,
                        help='crop validation (default: False)')
    parser.add_argument("--val_batch_size", type=int, default=4,
                        help='batch size for validation (default: 4)')
    parser.add_argument("--crop_size", type=int, default=513)

    
    parser.add_argument("--ckpt", default="checkpoints/best_deeplabv3plus_resnet101_cityscapes_os16.pth", type=str,
                        help="resume from checkpoint")
    parser.add_argument("--gpu_id", type=str, default='0',
                        help="GPU ID")
    return parser

def main():
    opts = get_argparser().parse_args()
    if opts.dataset.lower() == 'voc':
        opts.num_classes = 21
        decode_fn = VOCSegmentation.decode_target
    elif opts.dataset.lower() == 'cityscapes':
        opts.num_classes = 19
        decode_fn = Cityscapes.decode_target

    os.environ['CUDA_VISIBLE_DEVICES'] = opts.gpu_id
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print("Device: %s" % device)

    # Setup dataloader 
    processor = DataProcessor('results.json')
    train_buckets, val_buckets = processor.asc_buckets()
    if opts.val_data == "True":
        image_files = [d['image'] for d in val_buckets[opts.bucketidx]]
    else:
        image_files = [d['image'] for d in train_buckets[opts.bucketidx]] 

    print("\n\nNumber of images: %d" % len(image_files))
    
    
    
    # Set up model (all models are 'constructed at network.modeling)
    model = network.modeling.__dict__[opts.model](num_classes=opts.num_classes, output_stride=opts.output_stride)
    
    # we need to call the weak label generator here
    # labelgenerator(image_files, opts.model, opts.ckpt, opts.bucketidx)
    
    if opts.separable_conv and 'plus' in opts.model:
        network.convert_to_separable_conv(model.classifier)
    utils.set_bn_momentum(model.backbone, momentum=0.01)
    
    if opts.ckpt is not None and os.path.isfile(opts.ckpt):
        # https://github.com/VainF/DeepLabV3Plus-Pytorch/issues/8#issuecomment-605601402, @PytaichukBohdan
        checkpoint = torch.load(opts.ckpt, map_location=torch.device('cpu'))
        model.load_state_dict(checkpoint["model_state"])
        model = nn.DataParallel(model)
        model.to(device)
        print("Resume model from %s" % opts.ckpt)
        del checkpoint
    else:
        print("[!] Retrain")
        model = nn.DataParallel(model)
        model.to(device)

    #denorm = utils.Denormalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])  # denormalization for ori images
    print("Line 104")
    if opts.crop_val:
        transform = T.Compose([
                T.Resize(opts.crop_size),
                T.CenterCrop(opts.crop_size),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406],
                                std=[0.229, 0.224, 0.225]),
            ])
    else:
        transform = T.Compose([
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406],
                                std=[0.229, 0.224, 0.225]),
            ])
    # print(f"opts.crop_val: {opts.crop_val}, opts.crop_size: {opts.crop_size}")
    if opts.save_val_results_to is not None:
        if opts.val_data == "True":
            dir_name = os.path.join(opts.save_val_results_to, 'val_bucket_' + str(opts.bucketidx))
        else:
            dir_name = os.path.join(opts.save_val_results_to, 'bucket_' + str(opts.bucketidx))
        os.makedirs(dir_name, exist_ok=True)
    with torch.no_grad():
        print("Line 123")
        model = model.eval()
        entropy_values = []
        confidence_values = []
        
        for img_path in tqdm(image_files):
            ext = os.path.basename(img_path).split('.')[-1]
            img_name = os.path.basename(img_path)[:-len(ext)-1]
            img = Image.open(img_path).convert('RGB')
            img = transform(img).unsqueeze(0) # To tensor of NCHW
            img = img.to(device)
            
            # print(f"img.shape: {img.shape}")
            output = model(img)
            # print(f"output.shape: {output.shape}")

            # for i in range(output.shape[1]):
            #     print(f"output[{i}].shape: {output[0, i]}")

            pred = output.max(1)[1].cpu().numpy()[0] # HW
            # print(f"pred.shape: {pred.shape}")
            # print(pred)
            
            # Calculate confidence and average entropy for this image
            prob = torch.softmax(output, dim=1)
            confidence = prob.max(1)[0].mean().item()
            entropy = -torch.sum(prob * torch.log(prob + 1e-10), dim=1)  # HW
            avg_entropy = entropy.mean().item()
            entropy_values.append(avg_entropy)      
            confidence_values.append(confidence)     

            colorized_preds = decode_fn(pred).astype('uint8')
            colorized_preds = Image.fromarray(colorized_preds)
            colorized_preds = Image.fromarray(pred.astype('uint8'))
            if opts.save_val_results_to:
                colorized_preds.save(os.path.join(dir_name, img_name+'.png'))
            
        overall_avg_entropy = np.mean(entropy_values)
        overall_avg_confidence = np.mean(confidence_values)
        print(f"Overall average entropy for all images: {overall_avg_entropy:.4f}")
        print(f"Overall average confidence for all images: {overall_avg_confidence:.4f}")

if __name__ == '__main__':
    main()
