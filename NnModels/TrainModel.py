import csv
import pandas as pd
from rdkit import Chem
from sklearn.model_selection import train_test_split
import torch
import torch.utils.data as Data
from torch import nn
from torch.optim import SGD,Adam
from .MLPModel import nnModel0, nnModel1, nnModel2
from joblib import Parallel, delayed
csv.field_size_limit(500 * 1024 * 1024)
from rdkit.Chem import AllChem
import rdkit.Chem as Chem
import numpy as np
import pandas as pd
from rdkit.Chem import rdChemReactions
from rdkit.Chem.rdChemReactions import RemoveMappingNumbersFromReactions

def get_one_hot_tem(tem,teml):
    blist = []
    for i in list(tem):
        alist = [0]*teml
        alist[int(i)] = 1
        blist.append(alist)
    tems = torch.tensor(blist, dtype=torch.float32)
    return tems

def get_rxnfp(reaction):
    '''
    Get the fingerprint of the reaction.
    '''
    try:
        (reactant,product) = reaction
        rm = Chem.MolFromSmiles(reactant)
        pm = Chem.MolFromSmiles(product)
        info = {}
        rfpgen= np.array(AllChem.GetMorganFingerprintAsBitVect(rm, useChirality=True, radius=2, nBits = 512, bitInfo=info))
        pfpgen= np.array(AllChem.GetMorganFingerprintAsBitVect(pm, useChirality=True, radius=2, nBits = 512, bitInfo=info))
        rxnfp = pfpgen-rfpgen
        return (rfpgen,pfpgen,rxnfp)
    except Exception as e:
        print(e)
        return (None,None,None)

def get_conditionfp(condition):
    '''
    Get the fingerprint of the reaction conditions.
    '''
    try:
        condition = Chem.MolFromSmiles(condition)
        info = {}
        confp = np.array(AllChem.GetMorganFingerprintAsBitVect(condition, useChirality=True, radius=2, nBits = 512, bitInfo=info))
        return confp
    except Exception as e:
        print(e)
        return [0]*512
    

def get_train_data(inputs, path = 'data', file_name = '1976-2016_5+',withN = False, target = 'cat'):
    '''
    This function is used to get the data from the csv file.
    '''
    data = pd.read_csv('%s/%s.csv'%(path,file_name))
    if withN:
        file_name1 = "withN"
    else:
        file_name1 = "withoutN"

    if target in ['cat','solv']:
        with open('%s/all_%s_%s.csv'%(path,target,file_name1),'r') as f:
            reader = csv.DictReader(f)
            for classes in reader:
                target_list = list(classes.keys())
    elif target in ['reag0','reag1','reag2','reag3']:
        with open('%s/all_reag_%s.csv'%(path,file_name1),'r') as f:
            reader = csv.DictReader(f)
            for classes in reader:
                target_list = list(classes.keys())
    else:
        raise KeyError("target must be 'cat','solv','reag0','reag1','reag2','reag3'")

    print("n %s:"%target,len(target_list))

    rxnfps = Parallel(n_jobs=-1, verbose=4)(delayed(get_rxnfp)(reaction) for reaction in list(data[['reactants','products']].apply(tuple, axis=1)))
    t_data = []
    max_tem = 0
    if 'cat' in inputs:
        catfp = Parallel(n_jobs=-1, verbose=4)(delayed(get_conditionfp)(reaction) for reaction in data['cat'])
    if 'solv' in inputs:
        solvfp = Parallel(n_jobs=-1, verbose=4)(delayed(get_conditionfp)(reaction) for reaction in data['solv'])
    if 'reag0' in inputs:
        reagfp0 = Parallel(n_jobs=-1, verbose=4)(delayed(get_conditionfp)(reaction) for reaction in data['reag0'])
    if 'reag1' in inputs:
        reagfp1 = Parallel(n_jobs=-1, verbose=4)(delayed(get_conditionfp)(reaction) for reaction in data['reag1'])
    for i in range(len(rxnfps)):
        dic = {}
        if data[target][i] not in target_list:
            continue
        if rxnfps[i][0] is None:
            continue
        dic['input'] = np.concatenate((rxnfps[i][0],rxnfps[i][1]))
        if 'rxnfp' in inputs:
            dic['input'] =np.concatenate((dic['input'],rxnfps[i][2]))
        if 'cat' in inputs:
            dic['input'] = np.concatenate((dic['input'],catfp[i]))
        if 'solv' in inputs:
            dic['input'] = np.concatenate((dic['input'],solvfp[i]))
        if 'reag0' in inputs:
            dic['input'] = np.concatenate((dic['input'],reagfp0[i]))
        if 'reag1' in inputs:
            dic['input'] = np.concatenate((dic['input'],reagfp1[i]))
        dic['tem'] = data['template'][i]
        if data['template'][i] > max_tem:
            max_tem = data['template'][i]
        dic[target] = target_list.index(data[target][i])
        t_data.append(dic)
    print('n template:',max_tem+1)
    t_data = pd.DataFrame(t_data)
    print(len(t_data['input'][0]))
    return t_data,len(target_list),max_tem+1

def train_model(model,target, train_loader,test_loader,loss_function,Ir,epochs,withN):
    '''
    This function is used to train the model.
    '''
    optimizer = torch.optim.Adam(model.parameters(),lr=Ir)
    for epoch in range(epochs):
        running_loss = 0.0
        for step,data in enumerate(train_loader):
            optimizer.zero_grad()
            b_t = data[-1]
            out = model(data[:-1])
            loss = loss_function(out,b_t)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
            if step % 900 == 899:
                print('[%d, %5d] loss: %.3f' % (epoch + 1, step + 1, running_loss / 900))
                running_loss = 0.0
        test_model(model,test_loader,use_all=False)
    if withN:
        torch.save(model,'models/%s_model_withN.pt'%target)
    else:
        torch.save(model,'models/%s_model_withoutN.pt'%target)

def test_model(model,test_loader,use_all = True):
    '''
    This function is used to test the model.
    '''
    correct = 0
    total = 0
    with torch.no_grad(): 
        for step,data in enumerate(test_loader):
            b_t = data[-1]
            outputs = model(data[:-1])
            _, predicted = torch.max(outputs.data, dim = 1) 
            total += b_t.size(0)
            correct += (predicted == b_t).sum().item()
            if use_all == False and step >=100:
                break
    print('Accuracy on test set: %.4f' % (correct / total))

def topk_acc(model,test_loader,k):
    '''
    This function is used to calculate the topk accuracy.
    '''
    correct = 0
    total = 0
    with torch.no_grad():
        for step,data in enumerate(test_loader):
            b_t = data[-1]
            outputs = model(data[:-1])
            _, predicted = torch.topk(outputs.data, k = k, dim = 1)
            total += b_t.size(0)
            for i in range(len(predicted)):
                if b_t[i] in predicted[i]:
                    correct += 1
    print('Top%d acc: %.4f' % (k,correct / total))


def train_model_withT(teml,model,target, train_loader,test_loader,loss_function,Ir,epochs,withN):
    '''
    This function is used to train the model.
    '''
    optimizer = torch.optim.Adam(model.parameters(),lr=Ir)
    for epoch in range(epochs):
        running_loss = 0.0
        for step,(b_r,b_p,b_tem,b_t) in enumerate(train_loader):
            optimizer.zero_grad()
            b_tem = get_one_hot_tem(b_tem,teml)
            out = model((b_r,b_p,b_tem))
            loss = loss_function(out,b_t)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
            if step % 900 == 899:
                print('[%d, %5d] loss: %.3f' % (epoch + 1, step + 1, running_loss / 900))
                running_loss = 0.0
        acc = test_model_withT(teml,model,test_loader,use_all=False)
    if withN:
        torch.save(model,'models/%s_model_withN.pt'%target)
    else:
        torch.save(model,'models/%s_model_withoutN.pt'%target)

def test_model_withT(teml,model,test_loader,use_all = True):
    '''
    This function is used to test the model.
    '''
    correct = 0
    total = 0
    with torch.no_grad(): 
        for step,(b_x,b_p,b_tem,b_t) in enumerate(test_loader):
            b_tem = get_one_hot_tem(b_tem,teml)
            outputs = model((b_x,b_p,b_tem))
            _, predicted = torch.max(outputs.data, dim = 1) 
            total += b_t.size(0)
            correct += (predicted == b_t).sum().item()
            if use_all == False and step >=100:
                break
    print('Accuracy on test set: %.4f' % (correct / total))
    return correct / total

def topk_acc_withT(teml,model,test_loader,k):
    '''
    This function is used to calculate the topk accuracy.
    '''
    correct = 0
    total = 0
    with torch.no_grad():
        for step,(b_x,b_p,b_tem,b_t) in enumerate(test_loader):
            b_tem = get_one_hot_tem(b_tem,teml)
            outputs = model((b_x,b_p,b_tem))
            _, predicted = torch.topk(outputs.data, k = k, dim = 1)
            total += b_t.size(0)
            for i in range(len(predicted)):
                if b_t[i] in predicted[i]:
                    correct += 1
    print('Top%d acc: %.4f' % (k,correct / total))
    return correct / total

def train(inputs ,Model, path, file_name, withN, target, epochs, n1, n2, Ir, batch_size, loss_function = nn.CrossEntropyLoss()):
    print('start to get train data')
    data,targetl,teml = get_train_data(inputs,path, file_name, withN, target)
    input1 = inputs.split('+')
    if Model in [nnModel0,nnModel1]:
        X_train, X_test, y_train, y_test = train_test_split(data['input'], data[target], test_size=0.1)
        X_train_tensor = torch.tensor(list(X_train), dtype=torch.float32)
        y_train_tensor = torch.tensor(list(y_train), dtype=torch.int64)
        X_test_tensor = torch.tensor(list(X_test), dtype=torch.float32)
        y_test_tensor = torch.tensor(list(y_test), dtype=torch.int64)
        train_dataset = Data.TensorDataset(X_train_tensor, y_train_tensor)
        train_loader = Data.DataLoader(dataset=train_dataset, batch_size=batch_size, shuffle=True)
        test_dataset = Data.TensorDataset(X_test_tensor, y_test_tensor)
        test_loader = Data.DataLoader(dataset=test_dataset, batch_size=batch_size, shuffle=True)
        print('get data done')
        n0 = len(input1)*512
        print('n0:',n0)
        model = Model(targetl,n0,n1,n2)
        acc= train_model(model,target, train_loader,test_loader,loss_function = loss_function,Ir = Ir,epochs = epochs,withN = withN)
        print('------------------------------------')
        acc3 = topk_acc(model,test_loader,k=3)
        print('------------------------------------')
        acc10 = topk_acc(model,test_loader,k=10)
        print('------------------------------------')
        outdic = {'acc':acc,'acc3':acc3,'acc10':acc10}
        outdic = pd.DataFrame(outdic,index=[0])
        outdic.to_csv('models/%s_%s_out.csv'%(target,file_name))


    elif Model == nnModel2:
        X_train, X_test, y_train, y_test = train_test_split(data[['input','tem']], data[target], test_size=0.1)
        X_train_tensor0 = torch.tensor(list(X_train['input']), dtype=torch.float32)
        X_train_tensor2 = torch.tensor(list(X_train['tem']), dtype=torch.float32)
        y_train_tensor = torch.tensor(list(y_train), dtype=torch.int64)
        X_test_tensor0 = torch.tensor(list(X_test['input']), dtype=torch.float32)
        X_test_tensor2 = torch.tensor(list(X_test['tem']), dtype=torch.float32)
        y_test_tensor = torch.tensor(list(y_test), dtype=torch.int64)
        train_dataset = Data.TensorDataset(X_train_tensor0, X_train_tensor2, y_train_tensor)
        train_loader = Data.DataLoader(dataset=train_dataset, batch_size=batch_size, shuffle=True)
        test_dataset = Data.TensorDataset(X_test_tensor0, X_test_tensor2, y_test_tensor)
        test_loader = Data.DataLoader(dataset=test_dataset, batch_size=batch_size, shuffle=True)
        print('get data done')
        model = Model(targetl,teml,n1,n2)
        train_model_withT(teml,model,target, train_loader,test_loader,loss_function = loss_function,Ir = Ir,epochs = epochs,withN = withN)
        print('------------------------------------')
        topk_acc_withT(teml,model,test_loader,k=3)
        print('------------------------------------')
        topk_acc_withT(teml,model,test_loader,k=10)
        print('------------------------------------')
    

if __name__ == '__main__':
    from MLPModel import nnModel0, nnModel1, nnModel2
    train(Model = nnModel2 ,path = 'data', file_name = '1976-2016_5+',withN = False, target = 'cat', epochs = 1, n1=128, n2=32,Ir = 0.0001,batch_size = 128,loss_function = nn.CrossEntropyLoss(),)
