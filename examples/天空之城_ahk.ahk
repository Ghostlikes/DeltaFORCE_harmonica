; 天空之城 · 自动演奏脚本（由 harmonica/play.py 生成）
; 用法：装 AutoHotkey v2（autohotkey.com，约 3MB）→ 双击本文件 → 切到游戏窗口 → Ctrl+Alt+S 起弹，F10 随时中止
; 提示：本文件是「自带数据 + 忙等定时」的独立脚本，运行期间不需要 Python。
#Requires AutoHotkey v2.0
#SingleInstance Force
SendMode "Input"
SetKeyDelay -1, -1

DATA := "1,mdn,left;40,kdn,N;337,kup,N;385,kdn,M;690,kup,M;691,mup,left;730,kdn,Z;1716,kup,Z;1724,mdn,left;1764,kdn,M;2061,kup,M;2062,mup,left;2109,kdn,Z;2751,kup,Z;2799,kdn,C;3448,kup,C;3449,mdn,left;3488,kdn,M;5509,kup,M;5557,kdn,C;6207,kup,C;6247,kdn,N;7241,kup,N;7281,kdn,B;7586,kup,B;7626,kdn,N;8276,kup,N;8277,mup,left;8316,kdn,Z;8958,kup,Z;8966,mdn,left;9006,kdn,B;11026,kup,B;11074,kdn,C;11724,kup,C;11764,kdn,V;12759,kup,V;12799,kdn,C;13103,kup,C;13143,kdn,V;13448,kup,V;13449,mup,left;13488,kdn,Z;14475,kup,Z;14483,mdn,left;14523,kdn,C;16544,kup,C;16545,mup,left;16592,kdn,Z;17233,kup,Z;17241,mdn,left;17281,kdn,M;18268,kup,M;18276,mdn,middle;18316,kdn,V;18613,kup,V;18661,kdn,V;19655,kup,V;19656,mup,middle;19695,kdn,M;19992,kup,M;20040,kdn,M;22069,kup,M;22109,kdn,N;22414,kup,N;22454,kdn,M;22759,kup,M;22760,mup,left;22799,kdn,Z;23785,kup,Z;23793,mdn,left;23833,kdn,M;24130,kup,M;24131,mup,left;24178,kdn,Z;24820,kup,Z;24868,kdn,C;25517,kup,C;25518,mdn,left;25557,kdn,M;27578,kup,M;27626,kdn,C;27931,kup,C;27971,kdn,C;28276,kup,C;28316,kdn,N;29310,kup,N;29350,kdn,B;29655,kup,B;29695,kdn,N;30345,kup,N;30346,mup,left;30385,kdn,Z;31026,kup,Z;31034,mdn,left;31074,kdn,B;33095,kup,B;33143,kdn,C;33793,kup,C;33833,kdn,V;34483,kup,V;34484,mup,left;34523,kdn,Z;34820,kup,Z;34828,mdn,left;34868,kdn,M;35854,kup,M;35855,mup,left;35902,kdn,Z;36544,kup,Z;36592,kdn,X;37241,kup,X;37281,kdn,C;37586,kup,C;37626,kdn,Z;39310,kup,Z;39350,kdn,Z;39655,kup,Z;39656,mdn,left;39695,kdn,M;39992,kup,M;40040,kdn,N;40690,kup,N;40730,kdn,M;41379,kup,M;41380,mdn,middle;41419,kdn,B;42061,kup,B;42062,mup,middle;42109,kdn,N;44130,kup,N;44131,mup,left;44178,kdn,Z;44475,kup,Z;44523,kdn,X;44828,kup,X;44868,kdn,C;45862,kup,C;45902,kdn,X;46207,kup,X;46247,kdn,C;46897,kup,C;46937,kdn,B;47586,kup,B;47626,kdn,X;49655,kup,X;49656,mdn,left;49695,kdn,B;50337,kup,B;50338,mup,left;50385,kdn,Z;51371,kup,Z;51379,mdn,left;51419,kdn,M;51716,kup,M;51717,mup,left;51764,kdn,Z;52406,kup,Z;52454,kdn,X;52759,kup,X;52799,kdn,C;53103,kup,C;53143,kdn,C;55862,kup,C;55863,mdn,left;55902,kdn,N;56199,kup,N;56247,kdn,M;56552,kup,M;56553,mup,left;56592,kdn,Z;57233,kup,Z;57241,mdn,left;57281,kdn,M;57578,kup,M;57579,mup,left;57626,kdn,Z;57923,kup,Z;57971,kdn,X;58621,kup,X;58661,kdn,Z;59655,kup,Z;59656,mdn,left;59695,kdn,B;59992,kup,B;59993,mup,left;60040,kdn,B;61371,kup,B;61419,kdn,V;62069,kup,V;62109,kdn,C;62759,kup,C;62799,kdn,X;63448,kup,X;63488,kdn,Z;64138,kup,Z;64178,kdn,C;66207,kup,C;66247,kdn,C;66897,kup,C;66937,kdn,N;67931,kup,N;67971,kdn,N;68276,kup,N;68316,kdn,B;69310,kup,B;69350,kdn,B;69655,kup,B;69695,kdn,C;70000,kup,C;70040,kdn,X;70345,kup,X;70385,kdn,Z;71034,kup,Z;71074,kdn,Z;72414,kup,Z;72454,kdn,X;73448,kup,X;73488,kdn,Z;73793,kup,Z;73833,kdn,X;74483,kup,X;74523,kdn,B;75172,kup,B;75212,kdn,C;77241,kup,C;77281,kdn,C;77931,kup,C;77971,kdn,N;78966,kup,N;79006,kdn,N;79310,kup,N;79350,kdn,B;80345,kup,B;80385,kdn,B;80690,kup,B;80730,kdn,C;81034,kup,C;81074,kdn,X;81379,kup,X;81419,kdn,Z;82069,kup,Z;82109,kdn,Z;83448,kup,Z;83488,kdn,X;84483,kup,X;84523,kdn,Z;84828,kup,Z;84868,kdn,X;85517,kup,X;85518,mdn,left;85557,kdn,M;86199,kup,M;86247,kdn,N;88276,kup,N"
LEAD := 40      ; 起弹后第一个音的延时（= 修饰键提前量，倒计时是下面的 Sleep 3000）

QPC() {
    static f := 0, q := 0
    if !f
        DllCall("QueryPerformanceFrequency", "Int64*", &f)
    DllCall("QueryPerformanceCounter", "Int64*", &q)
    return q / f * 1000
}

Act(kind, arg) {
    down := (kind == "kdn" || kind == "mdn")
    if (arg == "left")
        SendEvent down ? "{LButton down}" : "{LButton up}"
    else if (arg == "right")
        SendEvent down ? "{RButton down}" : "{RButton up}"
    else if (arg == "middle")
        SendEvent down ? "{MButton down}" : "{MButton up}"
    else
        SendEvent "{" arg (down ? " down}" : " up}")
}

F10::ExitApp

^!s:: {
    global
    static busy := false
    if busy
        return
    busy := true
    SetTimer () => busy := false, -1000
    ToolTip "3 秒后开始，请切到游戏窗口（F10 中止）"
    Sleep 3000
    ToolTip
    t0 := QPC()
    Loop Parse, DATA, ";" {
        if (A_LoopField == "")
            continue
        p := StrSplit(A_LoopField, ",")
        while (QPC() - t0 < p[1] + LEAD)
            Sleep 1
        Act(p[2], p[3])
    }
}
