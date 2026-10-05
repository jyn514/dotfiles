" see https://github.com/shabiel/vim-mumps-tools/blob/master/vim/.vim/scripts.vim

" Mumps syntax file
" Language:	MUMPS
" Maintainer:	Jim Self, jaself@ucdavis.edu

" Quit when a (custom) syntax file was already loaded
if exists("b:current_syntax")
  finish
endif

" related formatting, jas 24Sept03 - experimental
set breakat=\ ,

" Remove any old syntax stuff hanging around
syn clear
syn sync    maxlines=0
syn sync    minlines=0
syn case    ignore

"errors
syn match   mumpsError          contained /[^ \t;].\+/
syn match   mumpsBadString 	/".*/
" Catch mismatched parentheses
syn match   mumpsParenError	/).*/
syn match   mumpsBadParen	/(.*/


" Line Structure
syn region  mumpsComment        start=";" end=/$/ keepend contains=mumpsTodo,mumpsCommentTitle
syn keyword  mumpsTodo   	contained TODO XXX FIX FIXME DEBUG DISABLED
syn match   mumpsCommentTitle   contained ":" contains=mumpsTodo

syn match   mumpsLabel  	contained /^[%A-Za-z][A-Za-z0-9]*\|^[0-9]\+/ nextgroup=mumpsFormalArgs
syn region  mumpsFormalArgs	contained oneline start=/(/ end=/)/ contains=mumpsLocalName,","
syn match   mumpsDotLevel	contained /\.[. \t]*/

syn region  mumpsCmd		contained oneline start=/[A-Za-z]/ end=/[ \t]/ end=/$/ contains=mumpsCommand,mumpsZCommand,mumpsPostCondition,mumpsError nextgroup=mumpsArgsSeg
syn region  mumpsPostCondition	contained oneline start=/:/hs=s+1 end=/[ \t]/re=e-1,he=e-1,me=e-1 end=/$/ contains=@mumpsExpr
syn region  mumpsArgsSeg	contained oneline start=/[ \t]/lc=1 end=/[ \t]\+/ end=/$/ contains=@mumpsExpr,",",mumpsPostCondition

syn match   mumpsLineStart      contained /^[ \t][. \t]*/ 
syn match   mumpsLineStart      contained /^[%A-Za-z][^ \t;]*[. \t]*/ contains=mumpsLabel,mumpsDotLevel 
syn region  mumpsLine		start=/^/ keepend end=/$/ contains=mumpsCmd,mumpsLineStart,mumpsComment

syn cluster mumpsExpr     	contains=mumpsVar,mumpsIntrinsic,mumpsExtrinsic,mumpsString,mumpsNumber,mumpsParen,mumpsOperator,mumpsBadString,mumpsBadNum,mumpsVRecord

syn match   mumpsVar		contained /\^\?[%A-Za-z][A-Za-z0-9]*/ nextgroup=mumpsSubs
syn match   mumpsIntrinsic 	contained /$[%A-Za-z][A-Za-z0-9]*/ contains=mumpsIntrinsicFunc,mumpsZInFunc,mumpsSpecialVar,mumpsZVar nextgroup=mumpsParams
syn match   mumpsExtrinsic	contained /$$[%A-Za-z][A-Za-z0-9]*\(^[%A-Za-z][A-Za-z0-9]*\)\=/ nextgroup=mumpsParams

syn match   mumpsLocalName	contained /[%A-Za-z][A-Za-z0-9]*/

" Operators
syn match   mumpsOperator       contained "[+\-*/=&#!'\\\]<>?@]"
syn match   mumpsOperator       contained "]]"
syn region  mumpsVRecord	contained start=/[= \t,]</lc=1 end=/>/ contains=mumpsLocalName,","

" Constants
syn region  mumpsString 	contained oneline start=/"/ skip=/""/ excludenl end=/"/ oneline
syn match   mumpsBadNum 	contained /\<0\d+\>/
syn match   mumpsBadNum 	contained /\<\d*\.\d*0\>/
syn match   mumpsNumber 	contained /\<\d*\.\d{1,9}\>/
syn match   mumpsNumber 	contained /\<\d\+\>/

syn region  mumpsParen     	contained oneline start=/(/ms=s+1 end=/)/me=e-1 contains=@mumpsExpr
syn region  mumpsSubs		contained oneline start=/(/ms=s+1 end=/)/me=e-1 contains=@mumpsExpr,","
syn region  mumpsActualArgs	contained oneline start=/(/ end=/)/ contains=@mumpsExpr,","

" Keyword definitions -------------------
"-- Commands --
syn keyword mumpsCommand	contained B[reak] C[lose] D[o] E[lse] F[or] G[oto] H[alt] H[ang]
syn keyword mumpsCommand 	contained I[f] J[ob] K[ill] L[ock] M[erge] N[ew] O[pen] Q[uit]
syn keyword mumpsCommand 	contained R[ead] S[et] TC[ommit] TRE[start] TRO[llback] TS[tart]
syn keyword mumpsCommand 	contained U[se] V[iew] W[rite] X[ecute] 

"  -- GT.M specific --
syn keyword mumpsZCommand 	contained ZA[llocate] ZB[reak] ZCOM[pile] ZC[ontinue] ZD[eallocate]
syn keyword mumpsZCommand 	contained ZED[it] ZG[oto] ZH[elp] ZL[ink] ZM[essage] ZP[rint]
syn keyword mumpsZCommand 	contained ZSH[ow] ZST[ep] ZSY[stem] ZTC[ommit] ZTS[tart]
syn keyword mumpsZCommand 	contained ZWI[thdraw] ZWR[ite] ZK[ill]

"  -- DTM specific --
"syn keyword mumpsZCommand 	contained  zC[all] zET[rap] zHT[rap] zIT[rap] zK[ill] zNS[pace]
"syn keyword mumpsZCommand 	contained  zQ[uit] zS[ave] zSync zTrap zUnRead zUse zzDevStat 
"syn keyword mumpsZCommand 	contained  zzDOS zzErr zzKeyPut zzLog zzNaked zzSetKey zzSwitch

"-- Intrinsic Functions
syn keyword mumpsIntrinsicFunc	contained A[scii] C[har] D[ata] E[xtract] F[ind] FN[umber] G[et]
syn keyword mumpsIntrinsicFunc	contained J[ustify] L[ength] N[ame] N[ext] O[rder] P[iece]
syn keyword mumpsIntrinsicFunc	contained Q[uery] R[andom] S[elect] T[ext] T[ranslate] V[iew]

"----> DTM Trig functions
"syn keyword mumpsZInFunc	contained zAbs zArcCos zArcSin zArcTan  
"syn keyword mumpsZInFunc	contained zCos zCot zCSC zExp zLn zLog
"syn keyword mumpsZInFunc	contained zSec zSin zSqr zTan zPower

"----> DTM Bitstring functions
"syn keyword mumpsZInFunc	contained zBitAnd zBitCount zBitFind 
"syn keyword mumpsZInFunc	contained zBitGet zBitLen zBitNot zBitOr 
"syn keyword mumpsZInFunc	contained zBitSet zBitStr zBitXor 

"----> DTM Mouse functions --
"syn keyword mumpsZInFunc	contained zMouseInit zMouseReset zMouseInfo zMouseShow zMouseHide
"syn keyword mumpsZInFunc	contained zMouseReport zMouseXYMax zMouseSetInrpt zMouseReportI
"syn keyword mumpsZInFunc	contained zMouseReportM zMouseReportP zMouseReportR zMousePut 
"syn keyword mumpsZInFunc	contained zMouseGetSV zMouseSetSV zMouseExclude zMouseLimits 
"syn keyword mumpsZInFunc	contained zMousePointerT zMouseCursor zMouseSave zMouseRestore

"----> DTM other functions --
"syn keyword mumpsZInFunc	contained zCall zConvert zCvt zCRC zD[ate] 
"syn keyword mumpsZInFunc	contained zDev zEName zJob zLA[scii] zLC[har] 
"syn keyword mumpsZInFunc	contained zOLen zO[rder] zPrevious zR[eference] zRNext
"syn keyword mumpsZInFunc	contained zwA[scii] zWC[har] zX[ecute] zzDec zzEnv zzHex

" -- GT.M z-functions --
syn keyword mumpsZInFunc	contained ZD[ate] ZM[essage] ZPARSE ZP[revious] ZSEARCH ZTRNLNM 

" Special Variables
syn keyword mumpsSpecialVar	contained D[evice] H[orolog] I[O] J[ob] K[ey] P[rincipal]
syn keyword mumpsSpecialVar	contained S[torage] T[est] TL[evel] TR[estart] X Y	

"-- DTM specific --
"syn keyword mumpsZVar	contained zA zB zD[ate] zDepth zDev	
"syn keyword mumpsZVar	contained zDevClass zDevixXlate zDevixInterp
"syn keyword mumpsZVar	contained zDevR zDevTerm zDevType zE zEName 
"syn keyword mumpsZVar	contained zErr[or] zETrap zH[orolog] zIOS zIOT 
"syn keyword mumpsZVar	contained zJob zMode zName zNode zzNode	
"syn keyword mumpsZVar	contained zNSpace zPI zP[iece] zR[eference] 
"syn keyword mumpsZVar	contained zS[torage] zT[rap] zVer[sion] zX zY zzB
"syn keyword mumpsZVar	contained zzBreak zzCompat zzEnv zzErr zzJobName 
"syn keyword mumpsZVar	contained zzLicense zzNaked zzSwitch 	

"-- GT.M specific --
syn keyword mumpsZVar	contained ZCSTATUS ZDIR[ectory] ZEDIT ZEOF ZGBL[dir]
syn keyword mumpsZVar	contained ZIO ZL[evel] ZPOS[ition] ZPROMP[t] ZRO[utines]
syn keyword mumpsZVar	contained ZSO[urce] ZS[tatus] ZSYSTEM ZT[rap] ZVER[sion]

" The default methods for highlighting.  Can be overridden later
hi default link mumpsCommand		Keyword
hi default link mumpsZCommand		Keyword
hi default link mumpsIntrinsicFunc   Function
hi default link mumpsZInFunc		Preproc
hi default link mumpsSpecialVar      Function
hi default link mumpsZVar		PreProc
hi default link mumpsLineStart	Statement
hi default link mumpsLabel		PreProc
hi default link mumpsFormalArgs	PreProc
hi default link mumpsDotLevel	PreProc
hi default link mumpsCmdSeg		Special
hi default link mumpsPostCondition	Conditional
hi default link mumpsCmd		Statement
hi default link mumpsVar		Identifier
hi default link mumpsLocalName	Identifier
hi default link mumpsActualArgs      Special
hi default link mumpsIntrinsic       Function
hi default link mumpsExtrinsic	Special
hi default link mumpsString		String
hi default link mumpsNumber		Number
hi default link mumpsOperator	Operator
hi default link mumpsComment		Comment
hi default link mumpsError		Error
hi default link mumpsBadNum		Error
hi default link mumpsBadString	Error
hi default link mumpsBadParen	Error
hi default link mumpsParenError	Error

hi default link mumpsTodo		Todo
hi default link mumpsCommentTitle	PreProc

let b:current_syntax = "mumps"

" vim: ts=8
