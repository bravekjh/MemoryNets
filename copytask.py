import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pickle
import argparse
from tensorboardX import SummaryWriter
import time
import glob
import os

from common import henaff_init, cayley_init, random_orthogonal_init
from utils import str2bool, select_network

parser = argparse.ArgumentParser(description='auglang parameters')

parser.add_argument('--net-type', type=str, default='RNN', choices=['RNN'], help='options: RNN')
parser.add_argument('--nhid', type=int, default=128, help='hidden size of recurrent net')
parser.add_argument('--cuda', type=str2bool, default=True, help='use cuda')
parser.add_argument('--T', type=int, default=300, help='delay between sequence lengths')
parser.add_argument('--random-seed', type=int, default=400, help='random seed')
parser.add_argument('--labels', type=int, default=8, help='number of labels in the output and input')
parser.add_argument('--c-length', type=int, default=10, help='sequence length')
parser.add_argument('--nonlin', type=str, default='modrelu',
                    choices=['none', 'relu', 'tanh', 'modrelu', 'sigmoid'],
                    help='non linearity none, relu, tanh, sigmoid')
parser.add_argument('--vari', type=str2bool, default=False, help='variable length')
parser.add_argument('--lr', type=float, default=2e-4)
parser.add_argument('--rinit', type=str, default="henaff", help='recurrent weight matrix initialization')
parser.add_argument('--iinit', type=str, default="xavier", help='input weight matrix initialization')
parser.add_argument('--batch', type=int, default=10)
parser.add_argument('--weight_decay', type=float, default=0)
parser.add_argument('--onehot', type=str2bool, default=False)
parser.add_argument('--alpha', type=float, default=0.99)

args = parser.parse_args()

if args.rinit == "cayley":
    rinit = cayley_init
elif args.rinit == "henaff":
    rinit = henaff_init
elif args.rinit == "random":
    rinit = random_orthogonal_init
elif args.rinit == 'xavier':
    rinit = nn.init.xavier_normal_
elif args.rinit == 'kaiming':
    iinit = nn.init.kaiming_normal_
if args.iinit == "xavier":
    iinit = nn.init.xavier_normal_
elif args.iinit == 'kaiming':
    iinit = nn.init.kaiming_normal_


def generate_copying_sequence(T, labels, c_length):
    items = [1, 2, 3, 4, 5, 6, 7, 8, 0, 9]
    x = []
    y = []

    ind = np.random.randint(labels, size=c_length)
    for i in range(c_length):
        x.append([items[ind[i]]])
    for i in range(T - 1):
        x.append([items[8]])
    x.append([items[9]])
    for i in range(c_length):
        x.append([items[8]])

    for i in range(T + c_length):
        y.append([items[8]])
    for i in range(c_length):
        y.append([items[ind[i]]])

    x = np.array(x)
    y = np.array(y)

    return torch.FloatTensor([x]), torch.LongTensor([y])


def create_dataset(size, T, c_length=10):
    d_x = []
    d_y = []
    for i in range(size):
        sq_x, sq_y = generate_copying_sequence(T, 8, c_length)
        sq_x, sq_y = sq_x[0], sq_y[0]
        d_x.append(sq_x)
        d_y.append(sq_y)  #

    d_x = torch.stack(d_x)
    d_y = torch.stack(d_y)
    return d_x, d_y


def onehot(inp):
    # print(inp.shape)
    onehot_x = inp.new_zeros(inp.shape[0], args.labels + 2)
    return onehot_x.scatter_(1, inp.long(), 1)


class Model(nn.Module):
    def __init__(self, hidden_size, rec_net):
        super(Model, self).__init__()
        self.rnn = rec_net

        self.lin = nn.Linear(hidden_size, args.labels + 1)
        self.hidden_size = hidden_size
        self.loss_func = nn.CrossEntropyLoss()

        nn.init.xavier_normal_(self.lin.weight)

    def forward(self, x, y):

        hidden = None
        hiddens = []
        loss = 0
        accuracy = 0
        for i in range(len(x)):
            if args.onehot:
                inp = onehot(x[i])
                hidden = self.rnn.forward(inp, hidden)
            else:
                hidden = self.rnn.forward(x[i], hidden)
            hidden.retain_grad()
            hiddens.append(hidden)
            out = self.lin(hidden)
            loss += self.loss_func(out, y[i].squeeze(1))

            if i >= T + args.c_length:
                preds = torch.argmax(out, dim=1)
                actual = y[i].squeeze(1)
                correct = preds == actual

                accuracy += correct.sum().item()

        accuracy /= (args.c_length * x.shape[1])
        loss /= (x.shape[0])
        return loss, accuracy, hiddens


def train_model(net, optimizer, batch_size, T, n_steps):
    save_norms = []
    accs = []
    losses = []

    for i in range(n_steps):

        s_t = time.time()
        if args.vari:
            T = np.random.randint(1, args.T)
        x, y = create_dataset(batch_size, T, args.c_length)

        if CUDA:
            x = x.cuda()
            y = y.cuda()
        x = x.transpose(0, 1)
        y = y.transpose(0, 1)

        optimizer.zero_grad()
        loss, accuracy, hidden_states = net.forward(x, y)

        loss_act = loss
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(net.parameters(), 'inf')
        save_norms.append(norm)

        losses.append(loss_act.item())

        optimizer.step()
        accs.append(accuracy)
        if writer:
            writer.add_scalar('Loss', loss.item(), i)
            writer.add_scalar('Accuracy', accuracy, i)
            writer.add_scalar('Grad Norms', norm, i)

        print('Update {}, Time for Update: {} , Average Loss: {}, Accuracy: {}'.format(i + 1, time.time() - s_t,
                                                                                       loss_act.item(), accuracy))

    with open(SAVEDIR + '{}_Train_Losses'.format(NET_TYPE), 'wb') as fp:
        pickle.dump(losses, fp)

    with open(SAVEDIR + '{}_Train_Accuracy'.format(NET_TYPE), 'wb') as fp:
        pickle.dump(accs, fp)

    with open(SAVEDIR + '{}_Grad_Norms'.format(NET_TYPE), 'wb') as fp:
        pickle.dump(save_norms, fp)

    save_checkpoint({
        'state_dict': net.state_dict(),
        'optimizer': optimizer.state_dict(),
        'time step': i
    },
        '{}_{}.pth.tar'.format(NET_TYPE, i)
    )

    return


def load_model(net, optimizer, fname):
    if fname == 'l':
        print(SAVEDIR)
        list_of_files = glob.glob(SAVEDIR + '*')
        print(list_of_files)
        latest_file = max(list_of_files, key=os.path.getctime)
        print('Loading {}'.format(latest_file))

        check = torch.load(latest_file)
        net.load_state_dict(check['state_dict'])
        optimizer.load_state_dict(check['optimizer'])

    else:
        check = torch.load(fname)
        net.load_state_dict(check['state_dict'])
        optimizer.load_state_dict(check['optimizer'])
    epoch = check['epoch']
    return net, optimizer, epoch


def save_checkpoint(state, fname):
    filename = SAVEDIR + fname
    torch.save(state, filename)


nonlins = ['relu', 'tanh', 'sigmoid', 'modrelu']
nonlin = args.nonlin.lower()

random_seed = args.random_seed
NET_TYPE = args.net_type
CUDA = args.cuda
decay = args.weight_decay

hidden_size = args.nhid
udir = 'HS_{}_NL_{}_lr_{}_BS_{}_rinit_{}_iinit_{}_decay_{}_alpha_{}'.format(hidden_size, nonlin, args.lr, args.batch,
                                                                            args.rinit, args.iinit, decay, args.alpha)
if args.onehot:
    udir = 'onehot/' + udir

if not args.vari:
    n_steps = 1500
    LOGDIR = './logs/copytask/{}/{}/{}/'.format(NET_TYPE, udir, random_seed)
    SAVEDIR = './saves/copytask/{}/{}/{}/'.format(NET_TYPE, udir, random_seed)
    print(SAVEDIR)
else:
    n_steps = 200000
    LOGDIR = './logs/varicopytask/{}/{}/{}/'.format(NET_TYPE, udir, random_seed)
    SAVEDIR = './saves/varicopytask/{}/{}/{}/'.format(NET_TYPE, udir, random_seed)
writer = None
# writer = SummaryWriter(LOGDIR)

torch.cuda.manual_seed(random_seed)
torch.manual_seed(random_seed)
np.random.seed(random_seed)

inp_size = 1
T = args.T
batch_size = args.batch
out_size = args.labels + 1
if args.onehot:
    inp_size = args.labels + 2
rnn = select_network(NET_TYPE, inp_size, hidden_size, nonlin, rinit, iinit, CUDA)
net = Model(hidden_size, rnn)
if CUDA:
    net = net.cuda()
    net.rnn = net.rnn.cuda()

print('Copy task')
print(NET_TYPE)
print('Cuda: {}'.format(CUDA))
print(nonlin)
print(hidden_size)

if not os.path.exists(SAVEDIR):
    os.makedirs(SAVEDIR)

optimizer = optim.RMSprop(net.parameters(), lr=args.lr, alpha=args.alpha, weight_decay=args.weight_decay)

with open(SAVEDIR + 'hparams.txt', 'w') as fp:
    for key, val in args.__dict__.items():
        fp.write(('{}: {}'.format(key, val)))
train_model(net, optimizer, batch_size, T, n_steps)