// Выгрузка стандартных картинок платформы для макетов форм (tools/form-mockup).
//
// Запуск: консоль кода или «Вычислить» отладчика в любой базе на нужной версии платформы.
// Код линейный, без процедур: консоли исполняют текст через Выполнить(). Перед запуском задать
// каталог выгрузки в первой строке кода. Каждая картинка записывается файлом
// <АнглийскоеИмя>.<формат> (БиблиотекаКартинок.Провести → Post.png), вариант «100 %» (плотность
// ldpi). Каталог затем передается импорту макета:
//   formmockup.py import <Form.form> -o model.json --std-pictures <каталог>
// или переменной окружения FORMMOCKUP_STD_PICTURES.
//
// Список имен - синтакс-помощник 8.3.27 и 8.5.1; картинки, которой нет в версии платформы,
// пропускаются и называются в итоговом сообщении.

КаталогВыгрузки = "<каталог выгрузки>";

Расширения = Новый Соответствие;
Расширения.Вставить(ФорматКартинки.PNG, "png");
Расширения.Вставить(ФорматКартинки.SVG, "svg");
Расширения.Вставить(ФорматКартинки.GIF, "gif");
Расширения.Вставить(ФорматКартинки.BMP, "bmp");
Расширения.Вставить(ФорматКартинки.JPEG, "jpg");
Расширения.Вставить(ФорматКартинки.Icon, "ico");

Подбор = Новый Соответствие;
Подбор.Вставить("screenDensity", "ldpi");

СписокКартинок = "
|АктивироватьЗадачу;ActivateTask
|АктивныеПользователи;ActiveUsers
|БизнесПроцесс;BusinessProcess
|БизнесПроцессОбъект;BusinessProcessObject
|ВводНаОсновании;InputOnBasis
|ВидРасчета;CalculationType
|ВложеннаяТаблица;NestedTable
|ВнешнийИсточникДанных;ExternalDataSource
|ВнешнийИсточникДанныхКуб;ExternalDataSourceCube
|ВнешнийИсточникДанныхКубТаблицаИзмерения;ExternalDataSourceCubeDimensionTable
|ВнешнийИсточникДанныхТаблица;ExternalDataSourceTable
|ВнешнийИсточникДанныхФункция;ExternalDataSourceFunction
|ВнешнийПользовательСистемыВзаимодействия;CollaborationSystemExternalUser
|ВосстановитьЗначения;RestoreValues
|Вперед;Forward
|ВыборКомпоновкиДанных;DataCompositionSelection
|ВыборКомпоновкиДанныхНедоступный;DataCompositionSelectionDisabled
|Выбрать;Select
|ВыбратьВерхнийУровень;ChooseTopLevel
|ВыбратьЗначение;ChooseValue
|ВыбратьТип;ChooseType
|ВывестиСписок;OutputList
|ВыполнитьЗадачу;ExecuteTask
|ГеографическаяСхема;GeographicalSchema
|ГрафическаяСхема;GraphicalSchema
|ГрупповоеОбсуждение;GroupConversation
|Дебет;Debit
|ДебетКредит;DebitCredit
|Дендрограмма;Dendrogram
|Диаграмма;Chart
|ДиаграммаГанта;GanttChart
|ДиалогВопрос;DialogQuestion
|ДиалогВосклицание;DialogExclamation
|ДиалогИнформация;DialogInformation
|ДиалогСтоп;DialogStop
|ДобавитьВИзбранное;AddToFavorites
|Документ;Document
|ДокументОбъект;DocumentObject
|ЖурналДокументов;DocumentJournal
|ЖурналРегистрации;EventLog
|ЖурналРегистрацииПоПользователю;EventLogByUser
|ЗагрузитьНастройкиОтчета;LoadReportSettings
|Задача;Task
|ЗадачаОбъект;TaskObject
|ЗакончитьРедактирование;EndEdit
|Закрыть;Close
|Заменить;Replace
|Записать;Write
|ЗаписатьИЗакрыть;WriteAndClose
|ЗаписатьИзменения;WriteChanges
|ЗатенитьФлажки;GrayedAll
|ЗафиксироватьТаблицу;FixTable
|ИерархическийПросмотр;HierarchicalView
|Избранное;Favorites
|Изменить;Change
|ИзменитьМасштаб;Zoom
|ИзменитьФорму;CustomizeForm
|Измерение;Dimension
|Информация;Information
|История;History
|ИсторияДанных;DataHistory
|ИсторияОтборов;FilterHistory
|ИсторияСообщений;MessageHistory
|Календарь;Calendar
|Калькулятор;Calculator
|Картинка;Picture
|КомандаМенюФункций;FunctionMenuCommand
|Константа;Constant
|КонструкторЗапроса;QueryWizard
|КонструкторЗапросаВложенныйЗапрос;QueryWizardNestedQuery
|КонструкторЗапросаВременнаяТаблица;QueryWizardTempTable
|КонструкторЗапросаГруппаВременныхТаблиц;QueryWizardTempTablesGroup
|КонструкторЗапросаЗаменитьТаблицу;QueryWizardReplaceTable
|КонструкторЗапросаОписаниеВременнойТаблицы;QueryWizardTempTableDescription
|КонструкторЗапросаОтображатьТаблицыИзменений;QueryWizardShowChangesTables
|КонструкторЗапросаПараметрыТаблицы;QueryWizardTableParameters
|КонструкторЗапросаСоздатьВложенныйЗапрос;QueryWizardCreateNestedQuery
|КонструкторЗапросаСоздатьЗапросУничтоженияВременнойТаблицы;QueryWizardCreateTempTableDropQuery
|КонструкторЗапросаСоздатьОписаниеВременнойТаблицы;QueryWizardCreateTempTableDescription
|КонструкторНастроекКомпоновкиДанных;DataCompositionSettingsWizard
|Кредит;Credit
|КритерийОтбора;FilterCriterion
|Лупа;Magnifier
|Назад;Back
|Найти;Find
|НайтиВДереве;FindInTree
|НайтиВСодержании;SyncContents
|НайтиВСписке;FindInList
|НайтиПоНомеру;FindByNumber
|НайтиПредыдущий;FindPrevious
|НайтиСледующий;FindNext
|НастроитьСписок;CustomizeList
|Настройка;Setting
|НастройкаСписка;ListSettings
|НастройкиОтчета;ReportSettings
|НачатьВидеоконференцию;StartVideoconference
|НеБеспокоить;DontDisturb
|НеОповещать;DontNotify
|НоваяВложеннаяСхемаКомпоновкиДанных;DataCompositionNewNestedScheme
|НоваяГруппировкаКомпоновкиДанных;DataCompositionNewGroup
|НоваяДиаграммаКомпоновкиДанных;DataCompositionNewChart
|НоваяТаблицаКомпоновкиДанных;DataCompositionNewTable
|НовоеОбсуждение;NewConversation
|НовоеОкно;NewWindow
|Обновить;Refresh
|Обработка;DataProcessor
|Обсуждения;Conversations
|Оповещать;Notify
|Оповещения;Notifications
|Остановить;Stop
|ОтборИСортировка;FilterAndSort
|ОтборКомпоновкиДанных;DataCompositionFilter
|ОтборКомпоновкиДанныхНедоступный;DataCompositionFilterDisabled
|ОтборПоВиду;FilterByType
|ОтборПоТекущемуЗначению;FilterByCurrentValue
|ОтключитьОтбор;ClearFilter
|ОткрытьСАвтономногоСервера;OpenFromStandaloneServer
|ОткрытьСОсновногоСервера;OpenFromMainServer
|ОткрытьФайл;OpenFile
|ОтменаПроведения;UndoPosting
|ОтменитьПоиск;CancelSearch
|ОтправитьСообщение;SendMessage
|ОтсортированоПоВозрастанию;SortedAsc
|ОтсортированоПоУбыванию;SortedDesc
|Отчет;Report
|ОформлениеВоcклицательныйЗнак;AppearanceExclamationMark
|ОформлениеДефисЖелтый;AppearanceDashYellow
|ОформлениеЗвездаЗаполненная;AppearanceStarFilled
|ОформлениеЗвездаЗаполненнаяНаполовину;AppearanceStarHalfFilled
|ОформлениеЗвездаПустая;AppearanceStarEmpty
|ОформлениеЗнакВосклицательныйЗнак;AppearanceExclamationMarkIcon
|ОформлениеЗнакКрест;AppearanceCrossIcon
|ОформлениеЗнакФлажок;AppearanceCheckIcon
|ОформлениеКвадратыЗаполненные;AppearanceBoxesFilled
|ОформлениеКвадратыЗаполненныеДва;AppearanceBoxesTwoFilled
|ОформлениеКвадратыЗаполненныеОдин;AppearanceBoxesOneFilled
|ОформлениеКвадратыЗаполненныеТри;AppearanceBoxesThreeFilled
|ОформлениеКвадратыПустые;AppearanceBoxesEmpty
|ОформлениеКрест;AppearanceCross
|ОформлениеКругЖелтый;AppearanceCircleYellow
|ОформлениеКругЗаполненный;AppearanceCircleFilled
|ОформлениеКругЗаполненныйНаДвеЧетверти;AppearanceCircleTwoFourthFilled
|ОформлениеКругЗаполненныйНаОднуЧетверть;AppearanceCircleOneFourthFilled
|ОформлениеКругЗаполненныйНаТриЧетверти;AppearanceCircleThreeFourthFilled
|ОформлениеКругЗеленый;AppearanceCircleGreen
|ОформлениеКругКрасный;AppearanceCircleRed
|ОформлениеКругПустой;AppearanceCircleEmpty
|ОформлениеКругЧерный;AppearanceCircleBlack
|ОформлениеСтрелкаВверхЗеленая;AppearanceUpArrowGreen
|ОформлениеСтрелкаВверхСерая;AppearanceUpArrowGray
|ОформлениеСтрелкаВнизКрасная;AppearanceDownArrowRed
|ОформлениеСтрелкаВнизСерая;AppearanceDownArrowGray
|ОформлениеСтрелкаВправоЖелтая;AppearanceRightArrowYellow
|ОформлениеСтрелкаВправоСерая;AppearanceRightArrowGray
|ОформлениеСтрелкаНаклоннаяВверхЖелтая;AppearanceUpInclineArrowYellow
|ОформлениеСтрелкаНаклоннаяВверхЗеленая;AppearanceUpInclineArrowGreen
|ОформлениеСтрелкаНаклоннаяВверхСерая;AppearanceUpInclineArrowGray
|ОформлениеСтрелкаНаклоннаяВнизЖелтая;AppearanceDownInclineArrowYellow
|ОформлениеСтрелкаНаклоннаяВнизКрасная;AppearanceDownInclineArrowRed
|ОформлениеСтрелкаНаклоннаяВнизСерая;AppearanceDownInclineArrowGray
|ОформлениеТреугольникВверхЗеленый;AppearanceUpTriangleGreen
|ОформлениеТреугольникВнизКрасный;AppearanceDownTriangleRed
|ОформлениеФлагЖелтый;AppearanceFlagYellow
|ОформлениеФлагЗеленый;AppearanceFlagGreen
|ОформлениеФлагКрасный;AppearanceFlagRed
|ОформлениеФлажок;AppearanceCheckBox
|Очистить;Clear
|Параметры;Parameters
|ПараметрыВыводаКомпоновкиДанных;DataCompositionOutputParameters
|ПараметрыВыводаКомпоновкиДанныхНедоступные;DataCompositionOutputParametersDisabled
|ПараметрыДанныхКомпоновкиДанных;DataCompositionDataParameters
|Переименовать;Rename
|ПерейтиВперед;GoForward
|ПерейтиККонцу;GoToEnd
|ПерейтиКНачалу;GoToBegin
|ПерейтиНазад;GoBack
|ПерейтиПоВнешнейНавигационнойСсылке;GotoExternalURL
|ПерейтиПоНавигационнойСсылке;GotoURL
|ПереключитьАктивность;SwitchActivity
|ПереместитьВверх;MoveUp
|ПереместитьВлево;MoveLeft
|ПереместитьВниз;MoveDown
|ПереместитьВправо;MoveRight
|ПеренестиЭлемент;MoveItem
|Перечисление;Enum
|Перечитать;Reread
|Печать;Print
|ПечатьСразу;PrintImmediately
|ПланВидовРасчета;ChartOfCalculationTypes
|ПланВидовРасчетаОбъект;ChartOfCalculationTypesObject
|ПланВидовХарактеристик;ChartOfCharacteristicTypes
|ПланВидовХарактеристикОбъект;ChartOfCharacteristicTypesObject
|ПланОбмена;ExchangePlan
|ПланОбменаОбъект;ExchangePlanObject
|ПланСчетов;ChartOfAccounts
|ПланСчетовОбъект;ChartOfAccountsObject
|ПовернутьПоЧасовойСтрелке;RotateClockwise
|ПовернутьПротивЧасовойСтрелки;RotateCounterclockwise
|ПоискДанных;DataSearch
|ПоказатьВСписке;ShowInList
|ПоказатьДанные;ShowData
|ПоказатьПароль;ShowPassword
|ПолеВводаВыбрать;InputFieldSelect
|ПолеВводаВыбратьТип;InputFieldChooseType
|ПолеВводаКалендарь;InputFieldCalendar
|ПолеВводаКалькулятор;InputFieldCalculator
|ПолеВводаОткрыть;InputFieldOpen
|ПолеВводаОчистить;InputFieldClear
|ПолучитьНавигационнуюСсылку;GetURL
|Пользователь;User
|ПользовательБезНеобходимыхСвойств;UserWithoutNecessaryProperties
|ПользовательИнтеграцииСистемыВзаимодействия;CollaborationSystemIntegrationUser
|ПользовательСАутентификацией;UserWithAuthentication
|ПользовательСистемыВзаимодействия;CollaborationSystemUser
|ПользовательскиеПоляКомпоновкиДанных;DataCompositionUserFields
|ПоляГруппировкиКомпоновкиДанных;DataCompositionGroupFields
|ПоляГруппировкиКомпоновкиДанныхНедоступные;DataCompositionGroupFieldsDisabled
|ПометитьНаУдаление;MarkToDelete
|ПорядокКомпоновкиДанных;DataCompositionOrder
|ПорядокКомпоновкиДанныхНедоступный;DataCompositionOrderDisabled
|Предыдущий;Previous
|Прикрепить;Attach
|Провести;Post
|ПроизвольноеВыражение;CustomExpression
|ПросмотрПоВладельцу;ViewByOwner
|ПрочитатьИзменения;ReadChanges
|РазвернутьВсе;ExpandAll
|РегистрБухгалтерии;AccountingRegister
|РегистрНакопления;AccumulationRegister
|РегистрРасчета;CalculationRegister
|РегистрСведений;InformationRegister
|РегистрСведенийЗапись;InformationRegisterRecord
|РегламентноеЗадание;ScheduledJob
|РегламентныеЗадания;ScheduledJobs
|РедактироватьВДиалоге;EditInDialog
|РежимПросмотраСписка;ListViewMode
|РежимПросмотраСпискаДерево;ListViewModeTree
|РежимПросмотраСпискаИерархическийСписок;ListViewModeHierarchicalList
|РежимПросмотраСпискаСписок;ListViewModeList
|Реквизит;Attribute
|Ресурс;Resource
|СвернутьВсе;CollapseAll
|СводнаяДиаграмма;PivotChart
|Свойства;Properties
|Сегодня;Today
|Символ;Char
|СинтаксическийКонтроль;CheckSyntax
|СкопироватьОбъект;CloneObject
|СкопироватьЭлементСписка;CloneListItem
|СкрытьПароль;HidePassword
|Следующий;Next
|СнятьФлажки;UncheckAll
|СоздатьГруппу;CreateFolder
|СоздатьНачальныйОбраз;CreateInitialImage
|СоздатьЭлементСписка;CreateListItem
|Сообщение;Message
|СортироватьСписок;SortList
|СортироватьСписокПоВозрастанию;SortListAsc
|СортироватьСписокПоУбыванию;SortListDesc
|Сортировка;Sort
|СохранитьЗначения;SaveValues
|СохранитьНастройкиОтчета;SaveReportSettings
|СохранитьФайл;SaveFile
|Справка;Help
|СправкаФормы;FormHelp
|Справочник;Catalog
|СправочникОбъект;CatalogObject
|СтандартнаяНастройкаКомпоновкиДанных;DataCompositionStandardSettings
|СтартБизнесПроцесса;BusinessProcessStart
|СформироватьОтчет;GenerateReport
|ТабличныйДокументВставитьПримечание;SpreadsheetInsertComment
|ТабличныйДокументВставитьРазрывСтраницы;SpreadsheetInsertPageBreak
|ТабличныйДокументОтображатьГруппировки;SpreadsheetShowGroups
|ТабличныйДокументОтображатьЗаголовки;SpreadsheetShowHeaders
|ТабличныйДокументОтображатьПримечания;SpreadsheetShowComments
|ТабличныйДокументОтображатьСетку;SpreadsheetShowGrid
|ТабличныйДокументТолькоПросмотр;SpreadsheetReadOnly
|ТабличныйДокументУдалитьПримечание;SpreadsheetDeleteComment
|ТабличныйДокументУдалитьРазрывСтраницы;SpreadsheetDeletePageBreak
|УвеличитьМасштаб;ZoomIn
|Удалить;Delete
|УдалитьНепосредственно;DeleteDirectly
|УменьшитьМасштаб;ZoomOut
|УправлениеПоиском;SearchControl
|УровеньВверх;LevelUp
|УровеньВниз;LevelDown
|УсловноеОформлениеКомпоновкиДанных;DataCompositionConditionalAppearance
|УсловноеОформлениеКомпоновкиДанныхНедоступное;DataCompositionConditionalAppearanceDisabled
|УстановитьВремя;SetTime
|УстановитьИнтервал;SetDateInterval
|УстановитьФлажки;CheckAll
|Форма;Form
|ФорматированнаяСтрока;FormattedString
|ХранилищеНастроек;SettingsStorage";

Пропущено = Новый Массив;
Записано = 0;
Строки = СтрРазделить(СписокКартинок, Символы.ПС, Ложь);
Для Каждого Строка Из Строки Цикл
	Части = СтрРазделить(СокрЛП(Строка), ";");
	Если Части.Количество() <> 2 Тогда
		Продолжить;
	КонецЕсли;
	ИмяКартинки = Части[0];
	ИмяФайла = Части[1];
	Попытка
		// Картинка - свойство БиблиотекаКартинок: по имени-строке к нему обращается только Вычислить
		Картинка = Вычислить("БиблиотекаКартинок." + ИмяКартинки);
		Данные = Картинка.ПолучитьДвоичныеДанные(Ложь, Подбор);
		Вариант = Новый Картинка(Данные);
		// Формат не распознан - «bin»: импорт определит его по содержимому файла
		Расширение = Расширения.Получить(Вариант.Формат());
		Если Расширение = Неопределено Тогда
			Расширение = "bin";
		КонецЕсли;
		Данные.Записать(КаталогВыгрузки + ПолучитьРазделительПути() + ИмяФайла + "." + Расширение);
		Записано = Записано + 1;
	Исключение
		Пропущено.Добавить(ИмяКартинки);
	КонецПопытки;
КонецЦикла;

Сообщение = Новый СообщениеПользователю;
Сообщение.Текст = СтрШаблон("Записано картинок: %1 в %2. Пропущено: %3 %4",
	Записано, КаталогВыгрузки, Пропущено.Количество(), СтрСоединить(Пропущено, ", "));
Сообщение.Сообщить();
