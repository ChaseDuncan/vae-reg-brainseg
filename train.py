import os
import sys
import time
import tabulate

import torch
import torch.optim as optim
import torch.nn as nn
import numpy as np
from torch.utils.tensorboard import SummaryWriter
import pickle
import argparse
import random
from utils import (
    save_checkpoint,
    load_data,
    train,
    validate,
    )

from torch.utils.data import DataLoader
from factory.scheduler import PolynomialLR
import losses
from model import vaereg
from data_loader import BraTSDataset

parser = argparse.ArgumentParser(description='Train glioma segmentation model.')
#parser.add_argument('--config')
# [meta]
# loss: vae
# 
# [data]
# #data_dir: /data/cddunca2/brats2018/training/
# data_dir: /dev/shm/brats2018/
# log_dir: ./logs/
# modes: ["t1", "t1ce", "t2", "flair"]
# labels: ["whole_tumor", "enhancing_tumor", "tumor_core"]
# debug: False
# dims: [160, 192, 128]
# 
# [train_params]
# deterministic_train: False
# batch_size: 3
# learning_rate: 1e-4
# weight_decay: 1e-5
# epochs: 300
# train_split: 1.0

# In this directory is stored the script used to start the training,
# the most recent and best checkpoints, and a directory of logs.
parser.add_argument('--dir', type=str, required=True, metavar='PATH',
    help='The directory to write all output to.')

parser.add_argument('--data_dir', type=str, required=True, metavar='PATH TO DATA',
    help='Path to where the data is located.')

parser.add_argument('--model', type=str, default=None, required=True, metavar='MODEL',
                        help='model name (default: None)')

parser.add_argument('--upsampling', type=str, default='bilinear', 
    choices=['bilinear', 'deconv'], 
    help='upsampling algorithm to use in decoder (default: bilinear)')

parser.add_argument('--loss', type=str, default='avgdice', 
    choices=['dice', 'recon', 'avgdice', 'vae'], 
    help='which loss to use during training (default: avgdice)')

parser.add_argument('--data_par', action='store_true', 
    help='data parellelism flag (default: off)')

parser.add_argument('--seed', type=int, default=1, metavar='S', 
    help='random seed (default: 1)')

parser.add_argument('--wd', type=float, default=1e-4, 
    help='weight decay (default: 1e-4)')

parser.add_argument('--resume', type=str, default=None, metavar='PATH',
                        help='checkpoint to resume training from (default: None)')

parser.add_argument('--epochs', type=int, default=100, metavar='N', 
    help='number of epochs to train (default: 100)')

parser.add_argument('--num_workers', type=int, default=4, metavar='N', 
    help='number of workers to assign to dataloader (default: 4)')

parser.add_argument('--batch_size', type=int, default=1, metavar='N', 
    help='batch_size (default: 1)')

parser.add_argument('--save_freq', type=int, default=25, metavar='N', 
    help='save frequency (default: 25)')

parser.add_argument('--eval_freq', type=int, default=5, metavar='N', 
    help='evaluation frequency (default: 5)')

parser.add_argument('--lr', type=float, default=1e-4, metavar='LR', 
    help='initial learning rate (default: 1e-4)')

# Currently unused.
parser.add_argument('--momentum', type=float, default=0.9, metavar='M', 
    help='SGD momentum (default: 0.9)')

args = parser.parse_args()
device = torch.device('cuda')

os.makedirs(f'{args.dir}/logs', exist_ok=True)
os.makedirs(f'{args.dir}/checkpoints', exist_ok=True)

#dims=[168, 198, 128]
dims=[128, 128, 128]
with open(os.path.join(args.dir, 'command.sh'), 'w') as f:
  f.write(' '.join(sys.argv))
  f.write('\n')

torch.manual_seed(args.seed)
torch.cuda.manual_seed(args.seed)
np.random.seed(args.seed)
random.seed(args.seed)
torch.manual_seed(args.seed)
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True

# TODO: move data into /dev/shm
brats_data = BraTSDataset(args.data_dir, dims=dims)
trainloader = DataLoader(brats_data, batch_size=args.batch_size, 
                        shuffle=True, num_workers=args.num_workers)

# TODO: Replace with builder.
if args.model == 'baseline':
  model = vaereg.UNet()
#<<<<<<< Updated upstream
#  model = nn.DataParallel(model)
#  model = model.to(device)
#if config.model_type == 'reconreg':
#=======
  #model = btseg.BraTSSegmentation()
  device_ids = [i for i in range(torch.cuda.device_count())]
  model = nn.DataParallel(model, device_ids)
  model = model.cuda()

if args.model == 'reconreg':
#>>>>>>> Stashed changes
  model = vaereg.ReconReg()
  model = model.to(device)

if args.model == 'vaereg':
  model = vaereg.VAEreg()
  device_ids = [i for i in range(torch.cuda.device_count())]
  model = nn.DataParallel(model, device_ids)
  model = model.cuda()

optimizer = \
    optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.wd)

start_epoch = 0
if args.resume:
  print("Resume training from %s" % args.resume)
  checkpoint = torch.load(args.resume)
  start_epoch = checkpoint["epoch"]
  model.load_state_dict(checkpoint["state_dict"])
  optimizer.load_state_dict(checkpoint["optimizer"])    

# TODO: optimizer factory, allow for SGD with momentum etx.
columns = ['ep', 'loss', 'dice_tc_agg',\
  'dice_et_agg', 'dice_ed_agg', 'dice_ncr', 'dice_et',\
  'dice_wt', 'time', 'mem_usage']

writer = SummaryWriter(log_dir=f'{args.dir}/logs')
scheduler = PolynomialLR(optimizer, args.epochs)
loss = losses.build(args.loss)

for epoch in range(start_epoch, args.epochs):
  time_ep = time.time()
  model.train()
  train(model, loss, optimizer, trainloader, device)
  
  if (epoch + 1) % args.save_freq == 0:
      save_checkpoint(
          f'{args.dir}/checkpoints',
          epoch + 1,
          state_dict=model.state_dict(),
          optimizer=optimizer.state_dict()
      )

  if (epoch + 1) % args.eval_freq == 0:
    # Evaluate on training data
    train_res = validate(model, loss, trainloader, device)
    time_ep = time.time() - time_ep
    memory_usage = torch.cuda.memory_allocated() / (1024.0 ** 3)
    values = [epoch + 1, train_res['train_loss'].data] \
          + train_res['train_dice_agg'].tolist() + train_res['train_dice'].tolist()\
          + [ time_ep, memory_usage] 
    table = tabulate.tabulate([values], columns, tablefmt="simple", floatfmt="8.4f")
    print(table)
  
  scheduler.step()
  # Log validation
  #writer.add_scalar('Loss/train', train_loss, epoch)
  #writer.add_scalar('Dice/train/ncr&net', train_dice[0], epoch)
  #writer.add_scalar('Dice/train/ed', train_dice[1], epoch)
  #writer.add_scalar('Dice/train/et', train_dice[2], epoch)
  #writer.add_scalar('Dice/train/et_agg', train_dice_agg[0], epoch)
  #writer.add_scalar('Dice/train/wt_agg', train_dice_agg[1], epoch)
  #writer.add_scalar('Dice/train/tc_agg', train_dice_agg[2], epoch)

  
