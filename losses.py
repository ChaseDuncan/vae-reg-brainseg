"""
Dice loss 3D
"""

import torch
import torch.nn as nn
from torch.nn import functional as F

class DiceLoss(nn.Module):
    def __init__(self):
        super(DiceLoss, self).__init__()


    def forward(self, preds, targets):
        ''' Expect preds and targets to each be 3xHxWxD.''' 
        target = targets['target']
        num_vec = 2*torch.einsum('cijk, cijk ->c', 
                [preds.squeeze(), target.squeeze()])
        denom = torch.einsum('cijk, cijk -> c', 
                [preds.squeeze(), preds.squeeze()]) +\
                torch.einsum('cijk, cijk -> c', 
                        [target.squeeze(), target.squeeze()])
        avg_dice = torch.sum(num_vec / denom) / 3.0
        if 1 - avg_dice < 0:
            import pdb; pdb.set_trace()
        return 1 - avg_dice

def dice_score(preds, targets):
    if isinstance(preds, tuple):
      preds = preds[0]
    
    num = 2*torch.einsum('bcijk, bcijk ->bc', [preds, targets])
    denom = torch.einsum('bcijk, bcijk -> bc', [preds, preds]) +\
        torch.einsum('bcijk, bcijk -> bc', [targets, targets]) + 1e-32
    proportions = torch.div(num, denom) 
    #return torch.einsum('bc->c', proportions)
    return proportions

def agg_dice_score(preds, targets):
  ''' Gives Dice score for sub-regions which are evaluated in the
  competition.
  '''
  if isinstance(preds, tuple):
    preds = preds[0]

  channel_shape = preds[:, 0, :, :, :].size()

  agg = torch.zeros(preds.size())
  et = torch.zeros(channel_shape)
  et[torch.where(preds[:, 2, :, :, :] > 0.5)] = 1
  et = et.unsqueeze(1)
  
  wt = torch.zeros(channel_shape)
  wt[torch.where((preds[:, 0, :, :, :] > 0.5) | 
  (preds[:, 1, :, :, :] > 0.5) | 
  (preds[:, 2, :, :, :] > 0.5) )] = 1
  wt = wt.unsqueeze(1)

  tc = torch.zeros(channel_shape)
  tc[torch.where((preds[:, 0, :, :, :] > 0.5) | (preds[:, 2, :, :, :] > 0.5) )] = 1
  tc = tc.unsqueeze(1)
  
  agg_preds = torch.cat((et, wt, tc), 1)

  et_target = torch.zeros(channel_shape)
  et_target[torch.where(targets[:, 2, :, :, :] > 0.5)] = 1
  et_target = et_target.unsqueeze(1) 

  wt_target = torch.zeros(channel_shape)
  wt_target[torch.where((targets[:, 0, :, :, :] > 0.5) | 
  (targets[:, 1, :, :, :] > 0.5) | (targets[:, 2, :, :, :] > 0.5) )] = 1
  wt_target = wt_target.unsqueeze(1)
  
  tc_target = torch.zeros(channel_shape)
  tc_target[torch.where((targets[:, 0, :, :, :] > 0.5) | 
  (targets[:, 2, :, :, :] > 0.5) )] = 1
  tc_target = tc_target.unsqueeze(1)

  agg_targets = torch.cat((et_target, wt_target, tc_target), 1)

  return dice_score(agg_preds, agg_targets)

class KLLoss(nn.Module):
  def __init__(self):
    super(KLLoss, self).__init__()

  def forward(self, mu, logvar, N):
    sum_square_mean = torch.einsum('i,i->', mu, mu)
    sum_log_var = torch.einsum('i->', logvar)
    sum_var = torch.einsum('i->', torch.exp(logvar))
    
    return float(1/N)*(sum_square_mean+sum_var-sum_log_var-N)


class VAEDiceLoss(nn.Module):
  def __init__(self, label_recon = False):
    super(VAEDiceLoss, self).__init__()
    self.dice = AvgDiceLoss()
    self.kl = KLLoss()
    self.label_recon = label_recon

  def forward(self, output, target):
    return self.dice(output['seg_map'], target['target'])\
        + 0.1*F.mse_loss(output['recon'], target['src'])\
        + 0.1*self.kl(output['mu'], output['logvar'], 256)


class AvgDiceLoss(nn.Module):
  def __init__(self):
    super(AvgDiceLoss, self).__init__()
  # Need a loss builder so we don't have to have superfluous arguments

  def forward(self, output, target):
    targets = target['target']
    proportions = dice_score(output, targets)
    proportions = torch.einsum('bc->b', proportions)\
            /torch.einsum('bcijk, bcijk->b', targets, targets)
    avg_dice = torch.einsum('b->', proportions) / target['target'].shape[0]
    return 1 - avg_dice


#class DiceLoss(nn.Module):
#  def __init__(self):
#    super(DiceLoss, self).__init__()
#
#  def forward(self, output, target):
#    targets = target['target']
#    channels_by_batch_size = targets.size()[1]*targets.size()[0]
#    return  channels_by_batch_size - torch.einsum('bc->', dice_score(output, targets))

class ReconRegLoss(nn.Module):
  def __init__(self):
    super(ReconRegLoss, self).__init__()
    self.dice = AvgDiceLoss()

  def forward(self, output_targets):
    output, target, src = output_targets
    preds, recon = output
    dice_loss = self.dice(output_targets)
    return dice_loss + 0.1*F.mse_loss(recon, src)

def build(loss):
  if loss == 'dice':
    return DiceLoss()
  if loss == 'recon':
    return ReconRegLoss()
  if loss == 'avgdice':
    return AvgDiceLoss()
  if loss == 'vae':
    return VAEDiceLoss()
