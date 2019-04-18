%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% EvaluateINRIA Function for getting an evaluation of the quality
% Input:  (1) name of the file generated by your method (see the GT.bmp for how to save your result)
%         (2) (INT default: 0)     the radius for the morphological opening
%         (3) (BOOL default: true) save the result
% Output: (1) TruePositive FalsePositive TrueNegative FalseNegative FalsePositiveRate TruePositiveRate FalseNegativeRate
%
%For road, radius 1
%For river, radius 0
%For texture, radius 0
% 25.01.13 Yannick Verdie
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
function[ data ] = EvaluateINRIA(input_image, gt_image, varargin)

%-----------------------------------parameters
narginchk(2, 3);

numvarargs = length(varargin);
if numvarargs > 3
    error('get_score:TooManyInputs','requires at most 2 optional inputs');
end

% set defaults for optional inputs
optargs = {0 true};
optargs(1:numvarargs) = varargin;
[radius save_txt] = optargs{:};
%-----------------------------------

im = gt_image; %imread(['GT.bmp']);
%[pathstr, name_file, ext] = fileparts(name_image);
imRJ = input_image; %imread(name_image);

Fim = imRJ(:,:,1) > 0;
Tim = im(:,:,1) > 0;

%take the inverse
% Fim = ~Fim; 
% Tim = ~Tim;
% We don't take the inverse anymore, because we invert outside the function

se1 = strel('disk',radius);
TP = sum(sum(Fim&Tim));
FP = sum(sum(imopen(Fim&~Tim,se1)));%opening to not penalyse too much mis-aligned or wrong road size
%FP = sum(sum(Fim&~Tim));
TN = sum(sum(~Fim&~Tim));
FN = sum(sum(imopen(~Fim&Tim,se1)));%opening to not penalyse too much mis-aligned or wrong road size
%FN = sum(sum(~Fim&Tim));

FPR = FP/(FP+TN);%
TPR = TP/(TP+FN);%
FNR = FN/(TP+FN);% 

N = TP + FN + TN + FP;
S = (TP + FN) ./ N;
P = (TP + FP) ./ N;
MCC = (TP ./ N - S .* P)./sqrt(P.*S.*(1-S).*(1-P)); 

format shortg;
data = [TP FP TN FN FPR TPR MCC];

% if (save_txt)
% dlmwrite([name_file '_data.txt'],data,'delimiter',' ','precision','%10.6g');
% end