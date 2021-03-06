import torch
import torch.nn as nn
import sparseconvnet as scn
import torch.nn.functional as F
from torch.autograd.variable import Variable

class UNet3D(nn.Module):
    """Sparse 3D Unet for voxel level prediction.

    Modified from shiba24/3d-unet and ellisdg/3DUnetCNN

    Parameters
    ---------
    in_channels : int
    n_classes : int
    """

    def __init__(self, in_channel, n_classes, batchnorm=True, droput=0.0):
        self.in_channel = in_channel
        self.n_classes = n_classes
        super(UNet3D, self).__init__()

        self.conv1_1 = self.encoder(in_channel, 32, bias=False, batchnorm=batchnorm)
        self.conv1_2 = self.encoder(32, 64, bias=False, batchnorm=batchnorm)
        self.pool1 = scn.MaxPooling(3, 2, 2)

        self.conv2_1 = self.encoder(64, 64, bias=False, batchnorm=batchnorm)
        self.conv2_2 = self.encoder(64, 128, bias=False, batchnorm=batchnorm)
        self.pool2 = scn.MaxPooling(3, 2, 2)

        self.conv3_1 = self.encoder(128, 128, bias=False, filter_stride=1, filter_size=3, batchnorm=batchnorm)
        self.conv3_2 = self.encoder(128, 256, bias=False, filter_stride=1, filter_size=3, batchnorm=batchnorm)
        self.pool3 = scn.MaxPooling(3, 2, 2)

        self.conv4_1 = self.encoder(256, 256, bias=False, batchnorm=batchnorm)
        self.conv4_2 = self.encoder(256, 512, bias=False, batchnorm=batchnorm)

        self.up5_1 = self.decoder(512, 512, filter_size=2, filter_stride=2, bias=False)
        self.up5_2 = scn.JoinTable()
        self.conv5_1 = self.encoder(256+512, 256, bias=False, batchnorm=batchnorm)
        self.conv5_2 = self.encoder(256, 256, bias=False, batchnorm=batchnorm)

        self.up6_1 = self.decoder(256, 256, filter_size=2, filter_stride=2, bias=False)
        self.up6_2 = scn.JoinTable()
        self.conv6_1 = self.encoder(128 + 256, 128, bias=False)
        self.conv6_2 = self.encoder(128, 128, bias=False)

        self.up7_1 = self.decoder(128, 128, filter_size=2, filter_stride=2, bias=False)
        self.up7_2 = scn.JoinTable()
        self.conv7_1 = self.encoder(64 + 128, 64, bias=False, batchnorm=batchnorm)
        self.conv7_2 = self.encoder(64, 64, bias=False, batchnorm=batchnorm)

        self.conv8 = self.encoder(64, n_classes, filter_size=1, bias=False, batchnorm=False)
        self.act = scn.Sigmoid()

        self.log_level = 0

    def input_spatial_size(self, out_size):
        return out_size

    def set_log_level(self, level=None):
        self.log_level = level or 0

    def encoder(self, in_channels, out_channels, filter_size=3, filter_stride=1, bias=True, batchnorm=True, submanifold=True, dropout=0.0):
        layer = scn.Sequential(
            scn.SubmanifoldConvolution(3, in_channels, out_channels, filter_size, bias) if submanifold \
                else scn.Convolution(3, in_channels, out_channels, filter_size, filter_stride, bias),
            scn.BatchNormReLU(out_channels) if batchnorm else scn.ReLU())
        if dropout > 0.0:
            layer.add(Dropout(dropout))
        return layer

    def decoder(self, in_channels, out_channels, filter_size, filter_stride=1, bias=True):
        layer = scn.Sequential(
            scn.Deconvolution(3, in_channels, out_channels, filter_size, filter_stride, bias),
            scn.ReLU())
        return layer

    def forward(self, x):
        verbose = self.log_level
        if verbose > 0: print "input", x, x.spatial_size.tolist(), x.features.size()
        if verbose > 1: print "   ", x.features.view(-1).cpu().data.numpy().tolist()

        conv1_1 = self.conv1_1(x)
        if verbose > 0: print "conv1_1", conv1, conv1.spatial_size.tolist(), conv1.features, conv1.features.size()
        if verbose > 1: print "   ", conv1.features

        conv1_2 = self.conv1_2(conv1_1)
        del conv1_1
        if verbose > 0: print "conv1_2", conv1, conv1.spatial_size.tolist(), conv1.features, conv1.features.size()
        if verbose > 1: print "   ", conv1.features

        pool1 = self.pool1(conv1_2)
        if verbose > 0: print "pool1", pool1.spatial_size.tolist(), pool1.features.size()
        if verbose > 1: print "   ", pool1.features

        conv2_1 = self.conv2_1(pool1)
        del pool1
        if verbose > 0: print "conv2_1", conv2.spatial_size.tolist(), conv2.features.size()
        if verbose > 1: print "   ", conv2.features

        conv2_2 = self.conv2_2(conv2_1)
        del conv2_1
        if verbose > 0: print "conv2_2", conv2.spatial_size.tolist(), conv2.features.size()
        if verbose > 1: print "   ", conv2.features

        pool2 = self.pool2(conv2_2)
        if verbose > 0: print "pool2", pool2.spatial_size.tolist(), pool2.features.size()
        if verbose > 1: print "   ", pool2.features

        conv3_1 = self.conv3_1(pool2)
        del pool2
        if verbose > 0: print "conv3_1", conv3.spatial_size.tolist(), conv3.features.size()
        if verbose > 1: print "   ", conv3.features

        conv3_2 = self.conv3_2(conv3_1)
        del conv3_1
        if verbose > 0: print "conv3_3", conv3.spatial_size.tolist(), conv3.features.size()
        if verbose > 1: print "   ", conv3.features

        pool3 = self.pool3(conv3_2)
        if verbose > 0: print "pool3", pool3.spatial_size.tolist(), pool3.features.size()
        if verbose > 1: print "   ", pool3.features

        conv4_1 = self.conv4_1(pool3)
        del pool3
        if verbose > 0: print "conv4_1", conv4.spatial_size.tolist(), conv4.features.size()
        if verbose > 1: print "   ", conv4.features

        conv4_2 = self.conv4_2(conv4_1)
        del conv4_1
        if verbose > 0: print "conv4_2", conv4.spatial_size.tolist(), conv4.features.size()
        if verbose > 1: print "   ", conv4.features

        up5_1 = self.up5_1(conv4_2)
        del conv4_2
        if verbose > 0: print "up5_1", up5.spatial_size.tolist(), up5.features.size()
        if verbose > 1: print "   ", up5.features

        up5_2 = self.up5_2((up5_1, conv3_2))
        del up5_1
        del conv3_2
        if verbose > 0: print "up5_2", up5.spatial_size.tolist(), up5.features.size()
        if verbose > 1: print "   ", up5.features

        conv5_1 = self.conv5_1(up5_2)
        del up5_2
        if verbose > 0: print "conv5_1", conv5.spatial_size.tolist(), conv5.features.size()
        if verbose > 1: print "   ", conv5.features

        conv5_2 = self.conv5_2(conv5_1)
        del conv5_1
        if verbose > 0: print "conv5_2", conv5.spatial_size.tolist(), conv5.features.size()
        if verbose > 1: print "   ", conv5.features

        up6_1 = self.up6_1(conv5_2)
        del conv5_2
        if verbose > 0: print "up6_1", up6.spatial_size.tolist(), up6.features.size()
        if verbose > 1: print "   ", up6.features

        up6_2 = self.up6_2((up6_1, conv2_2))
        del up6_1
        del conv2_2
        if verbose > 0: print "up6_2", up6.spatial_size.tolist(), up6.features.size()
        if verbose > 1: print "   ", up6.features

        conv6_1 = self.conv6_1(up6_2)
        del up6_2
        if verbose > 0: print "conv6_1", conv6.spatial_size.tolist(), conv6.features.size()
        if verbose > 1: print "   ", conv6.features

        conv6_2 = self.conv6_2(conv6_1)
        del conv6_1
        if verbose > 0: print "conv6_2", conv6.spatial_size.tolist(), conv6.features.size()
        if verbose > 1: print "   ", conv6.features

        up7_1 = self.up7_1(conv6_2)
        del conv6_2
        if verbose > 0: print "up7_1", up7.spatial_size.tolist(), up7.features.size()
        if verbose > 1: print "   ", up7.features

        up7_2 = self.up7_2((up7_1, conv1_2))
        del up7_1
        del conv1_2
        if verbose > 0: print "up7_2", up7.spatial_size.tolist(), up7.features.size()
        if verbose > 1: print "   ", up7.features

        conv7_1 = self.conv7_1(up7_2)
        del up7_2
        if verbose > 0: print "conv7_1", conv7.spatial_size.tolist(), conv7.features.size()
        if verbose > 1: print "   ", conv7.features

        conv7_2 = self.conv7_2(conv7_1)
        del conv7_1
        if verbose > 0: print "conv7_2", conv7.spatial_size.tolist(), conv7.features.size()
        if verbose > 1: print "   ", conv7.features

        conv8 = self.conv8(conv7_2)
        del conv7_2
        if verbose > 0: print "conv8", conv8.spatial_size.tolist(), conv8.features.size()
        if verbose > 1: print "   ", conv8.features

        act = self.act(conv8)
        del conv8

        return act.features

class ResNetUNet(nn.Module):
    def __init__(self, nInputFeatures, nClasses, dropout_depth=False, dropout_width=False, dropout_p=0.5, wide_model=False, old_version=False):
        nn.Module.__init__(self)
        self.sparseModel = scn.Sequential().add(
            scn.ValidConvolution(3, nInputFeatures, 64, 3, False)).add(
            ResNetUNetDropout(3, 64, 2, 4, dropout_depth=dropout_depth, dropout_width=dropout_width, dropout_p=dropout_p) \
               if dropout_depth or dropout_width else scn.ResNetUNet(3, 64, 2, 4))

        self.use_wide_model = wide_model
        if wide_model:
            self.wide = nn.Linear(nInputFeatures, 1)
            #self.wide_and_deep = scn.JoinTable()
            self.linear = nn.Linear(65, nClasses)
            print "Using wide model"
        else:
            self.linear = nn.Linear(64, nClasses)

        self.act = nn.Softmax(dim=1)

        #Some older models still have this in, but it's not called
        if old_version:
            self.final = scn.ValidConvolution(3, 64, nClasses, 1, False)
            self.relu = scn.ReLU()

    def forward(self, x):
        x1 = self.sparseModel(x)
        #x2 = self.final(x1)
        if self.use_wide_model:
            x1_wide = self.wide(x.features)
            x_wide_deep = torch.cat((x1.features, x1_wide), 1) #self.wide_and_deep((x1, x1_wide))
            x2 = self.linear(x_wide_deep)
            del x1_wide
            del x_wide_deep
        else:
            x2 = self.linear(x1.features)
        del x1
        #x3 = self.relu(x2)
        x3 = self.act(x2)
        del x2
        #x4 = self.act(x3)
        #del x3
        return x3

def ResNetUNetDropout(dimension, nPlanes, reps, depth=4, dropout_p=0.5, dropout_depth=False, dropout_width=False):
    """
    U-Net style network with ResNet-style blocks.
    For voxel level prediction:
    import sparseconvnet as scn
    import torch.nn
    class Model(nn.Module):
        def __init__(self):
            nn.Module.__init__(self)
            self.sparseModel = scn.Sequential().add(
               scn.ValidConvolution(3, nInputFeatures, 64, 3, False)).add(
               scn.ResNetUNet(3, 64, 2, 4))
            self.linear = nn.Linear(64, nClasses)
        def forward(self,x):
            x=self.sparseModel(x).features
            x=self.linear(x)
            return x
    """
    def _res_dropout(m, a, b, p):
        m.add(scn.ConcatTable()
              .add(scn.Identity() if a == b else scn.NetworkInNetwork(a, b, False))
              .add(scn.Sequential()
                   .add(scn.BatchNormReLU(a))
                   .add(Dropout(p))
                   .add(scn.SubmanifoldConvolution(dimension, a, b, 3, False))
                   .add(scn.BatchNormReLU(b))
                   .add(scn.Dropout(p))
                   .add(scn.SubmanifoldConvolution(dimension, b, b, 3, False))))\
         .add(scn.AddTable())

    def _res(m, a, b, p):
        m.add(scn.ConcatTable()
              .add(scn.Identity() if a == b else scn.NetworkInNetwork(a, b, False))
              .add(scn.Sequential()
                   .add(scn.BatchNormReLU(a))
                   .add(scn.SubmanifoldConvolution(dimension, a, b, 3, False))
                   .add(scn.BatchNormReLU(b))
                   .add(scn.SubmanifoldConvolution(dimension, b, b, 3, False))))\
         .add(scn.AddTable())

    res = _res_dropout if dropout_depth else _res

    def v(depth, nPlanes):
        m = scn.Sequential()
        if depth == 1:
            for _ in range(reps):
                res(m, nPlanes, nPlanes, dropout_p)
        else:
            m = scn.Sequential()
            for _ in range(reps):
                res(m, nPlanes, nPlanes, dropout_p)
            if dropout_width:
                m.add(
                    scn.ConcatTable() .add(
                        scn.Identity()) .add(
                        scn.Sequential() .add(
                            scn.BatchNormReLU(nPlanes)) .add(
                            #In place of Maxpooling
                            scn.Convolution(
                                dimension,
                                nPlanes,
                                nPlanes,
                                2,
                                2,
                                False)) . add(
                            scn.Dropout(dropout_p)) .add(
                                v(
                                    depth - 1,
                                    nPlanes)) .add(
                                        scn.BatchNormReLU(nPlanes)) .add(
                                            scn.Deconvolution(
                                                dimension,
                                                nPlanes,
                                                nPlanes,
                                                2,
                                                2,
                                                False))))
            else:
                m.add(
                scn.ConcatTable() .add(
                    scn.Identity()) .add(
                    scn.Sequential() .add(
                        scn.BatchNormReLU(nPlanes)) .add(
                        scn.Convolution(
                            dimension,
                            nPlanes,
                            nPlanes,
                            2,
                            2,
                            False)) .add(
                            v(
                                depth - 1,
                                nPlanes)) .add(
                                    scn.BatchNormReLU(nPlanes)) .add(
                                        scn.Deconvolution(
                                            dimension,
                                            nPlanes,
                                            nPlanes,
                                            2,
                                            2,
                                            False))))
            m.add(scn.JoinTable())
            for i in range(reps):
                res(m, 2 * nPlanes if i == 0 else nPlanes, nPlanes, dropout_p)
        return m
    m = v(depth, nPlanes)
    m.add(scn.BatchNormReLU(nPlanes))
    return m

class RegularDropout(nn.Module):
    def __init__(self, p = 0.5):
        nn.Module.__init__(self)
        self.p = p
    def forward(self, input):
        output = scn.SparseConvNetTensor()
        i = input.features.data
        if self.training:
            m = i.new().resize_(1).expand_as(i).fill_(1-self.p)
            output.features = Variable(i * torch.bernoulli(m), requires_grad=input.features.requires_grad)
        else:
            output.features = Variable(i * (1 - self.p), requires_grad=input.features.requires_grad)
        output.metadata = input.metadata
        output.spatial_size = input.spatial_size
        return output
    def input_spatial_size(self, out_size):
        return out_size

class Dropout(nn.Module):
    """Batchwise Dropout"""
    def __init__(self, p = 0.5):
        nn.Module.__init__(self)
        self.p = p
    def forward(self, input):
        output = scn.SparseConvNetTensor()
        i = input.features.data
        if self.training:
            m = i.new().resize_(1).expand(1,i.shape[1]).fill_(1-self.p)
            output.features = Variable(i * torch.bernoulli(m), requires_grad=input.features.requires_grad)
        else:
            output.features = Variable(i * (1 - self.p), requires_grad=input.features.requires_grad)
        output.metadata = input.metadata
        output.spatial_size = input.spatial_size
        return output
    def input_spatial_size(self, out_size):
        return out_size

class SuperfamilyAutoEncoder(nn.Module):
    def __init__(self, size, nFeaturesTotal):
        self.dimension = 3
        self.reps = 1 #Conv block repetition factor
        self.m = 32 #Unet number of features
        self.nPlanes = [m, 2*m, 3*m, 4*m, 5*m] #UNet number of features per level
        nn.Module.__init__(self)
        self.sparseModel = scn.Sequential().add(
           scn.InputLayer(self.dimension, torch.LongTensor([size]*3), mode=3)).add(
           scn.SubmanifoldConvolution(self.dimension, 1, self.m, 3, False)).add(
           scn.UNet(self.dimension, self.reps, self.nPlanes, residual_blocks=False, downsample=[2,2])).add(
           scn.BatchNormReLU(self.m)).add(
           scn.OutputLayer(self.dimension))
        self.linear = nn.Linear(m, nFeaturesTotal)
    def forward(self,x):
        x=self.sparseModel(x)
        x=self.linear(x)
        return x

class SuperfamilySegmenter(nn.Module):
    def __init__(self, size):
        self.dimension = 3
        self.reps = 1 #Conv block repetition factor
        self.m = 32 #Unet number of features
        self.nPlanes = [m, 2*m, 3*m, 4*m, 5*m] #UNet number of features per level
        nn.Module.__init__(self)
        self.sparseModel = scn.Sequential().add(
           scn.InputLayer(self.dimension, torch.LongTensor([size]*3), mode=3)).add(
           scn.SubmanifoldConvolution(self.dimension, 1, self.m, 3, False)).add(
           scn.UNet(self.dimension, self.reps, self.nPlanes, residual_blocks=False, downsample=[2,2])).add(
           scn.BatchNormReLU(self.m)).add(
           scn.OutputLayer(self.dimension))
        self.linear = nn.Linear(m, 2)
    def forward(self,x):
        x=self.sparseModel(x)
        x=self.linear(x)
        return x
